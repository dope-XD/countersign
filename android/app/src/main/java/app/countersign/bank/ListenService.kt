package app.countersign.bank

import android.Manifest
import android.accessibilityservice.AccessibilityService
import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.provider.Settings
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import app.countersign.bank.data.RealRepository
import app.countersign.bank.data.Repo
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import kotlin.math.max

/**
 * The call listener's ears and eyes (docs/agents/platform.md, "Call listener"). An accessibility
 * service, because Android lets one keep the microphone during a call, which ordinary apps can't.
 *
 * - Records the mic, 16 kHz mono, only while a call is on and the user has listening on; the frames
 *   go to [audio] in memory for the speech-to-text and the stronger check. Never written anywhere.
 * - Says which app is in front ([foreground]), for the pay guard and the "remote-access / payment
 *   app opened" signals.
 * - Says whether the call is on speaker ([onSpeaker]): only then does the mic hear the caller.
 * - Hosts the call card as an accessibility overlay ([Overlay] asks [host]).
 */
class ListenService : AccessibilityService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var audioManager: AudioManager
    private var speakerListener: AudioManager.OnCommunicationDeviceChangedListener? = null

    @Volatile private var recorder: Thread? = null

    override fun onServiceConnected() {
        audioManager = getSystemService(AudioManager::class.java)
        _host.value = this
        speakerListener = AudioManager.OnCommunicationDeviceChangedListener { readSpeaker() }.also {
            audioManager.addOnCommunicationDeviceChangedListener(mainExecutor, it)
        }
        readSpeaker()
        val repo = Repo.instance
        scope.launch {
            // record while there's a call and listening is on; stop the moment either ends
            combine(repo.call, repo.home) { call, home -> call != null && home?.me?.listenCalls != false }
                .distinctUntilChanged()
                .collect { on -> if (on) startRecording() else stopRecording() }
        }
        (repo as? RealRepository)?.checkPermissions()
        // Android brings this service back by itself after an update or a crash; bring the call watcher with it
        runCatching { CallWatchService.start(this) }.onFailure { Log.w(TAG, "call watcher not started: $it") }
        Log.i(TAG, "listening service on")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            event.packageName?.toString()?.takeIf { it != _foreground.value }?.let {
                _foreground.value = it
                Log.d(TAG, "in front: $it")
            }
        }
    }

    override fun onInterrupt() {}

    override fun onDestroy() {
        stopRecording()
        speakerListener?.let { audioManager.removeOnCommunicationDeviceChangedListener(it) }
        scope.cancel()
        if (_host.value === this) _host.value = null
        _onSpeaker.value = false
        (Repo.instance as? RealRepository)?.checkPermissions()
        super.onDestroy()
    }

    private fun readSpeaker() {
        _onSpeaker.value = audioManager.communicationDevice?.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER
    }

    private fun startRecording() {
        if (recorder != null) return
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            Log.w(TAG, "no microphone permission: not listening")
            return
        }
        recorder = Thread({ record() }, "listen").apply { start() }
    }

    private fun stopRecording() {
        recorder?.interrupt()
        recorder = null
        _recording.value = false
    }

    @Suppress("MissingPermission") // checked in startRecording
    private fun record() {
        val minBuf = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = try {
            AudioRecord(SOURCE, RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, max(minBuf, RATE / 2))
        } catch (e: Exception) {
            Log.w(TAG, "mic not opened: $e")
            return
        }
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            Log.w(TAG, "mic not initialised")
            rec.release()
            return
        }
        try {
            rec.startRecording()
            _recording.value = true
            val frame = ShortArray(FRAME)
            var frames = 0
            while (!Thread.currentThread().isInterrupted) {
                val n = rec.read(frame, 0, frame.size)
                if (n > 0 && !feeding) _audio.tryEmit(frame.copyOf(n)) // a copy each time: listeners keep frames while this one refills
                if (++frames == 50) { // a second in: did Android let us hear the call? (#37)
                    val silenced = audioManager.activeRecordingConfigurations.firstOrNull { it.clientAudioSessionId == rec.audioSessionId }?.isClientSilenced
                    Log.i(TAG, "recording the call, silenced=$silenced, speaker=${_onSpeaker.value}")
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "recording stopped: $e")
        } finally {
            runCatching { rec.stop() }
            rec.release()
            if (recorder == null || recorder === Thread.currentThread()) _recording.value = false // not if a new call already started
        }
    }

    companion object {
        private const val TAG = "Listen"
        const val RATE = 16_000

        /** 20 ms. */
        const val FRAME = RATE / 50

        /**
         * The only source an accessibility service wasn't silenced on during a call (emulator,
         * Android 15; #37). The real-phone runs of #37 decide this per phone maker.
         */
        private const val SOURCE = MediaRecorder.AudioSource.VOICE_RECOGNITION

        private val _host = MutableStateFlow<ListenService?>(null)

        /** The running service, to host the call card; null when accessibility is off. */
        val host: StateFlow<ListenService?> = _host

        private val _audio = MutableSharedFlow<ShortArray>(extraBufferCapacity = 50) // 1 s of slack for slow listeners
        private val _foreground = MutableStateFlow<String?>(null)
        private val _onSpeaker = MutableStateFlow(false)
        private val _recording = MutableStateFlow(false)

        /** The call's audio while it's being recorded: 20 ms frames of 16 kHz mono PCM. Memory only. */
        val audio: SharedFlow<ShortArray> = _audio

        /** Package name of the app in front, from window changes. */
        val foreground: StateFlow<String?> = _foreground
        val onSpeaker: StateFlow<Boolean> = _onSpeaker
        val recording: StateFlow<Boolean> = _recording

        /** Debug builds only (spike/FeedAudio.kt): frames from a file, as if the mic heard them; the mic's own frames wait meanwhile. */
        @Volatile var feeding = false

        fun feed(frame: ShortArray): Boolean = BuildConfig.DEBUG && _audio.tryEmit(frame)

        /** Whether the user has turned this service on under Accessibility. */
        fun enabled(c: Context): Boolean {
            val me = ComponentName(c, ListenService::class.java).flattenToString()
            val on = Settings.Secure.getString(c.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES).orEmpty()
            return on.split(':').any { it.equals(me, ignoreCase = true) }
        }
    }
}
