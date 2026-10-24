package app.countersign.bank.spike

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import app.countersign.bank.ListenService
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Debug builds only: plays a 16 kHz mono 16-bit WAV into the call listener as if the mic heard it, so the live
 * pipeline (VAD → speech-to-text → Analyzer → the card, the scam alert) can be tested on an emulator call.
 *
 *   adb push call.wav /sdcard/Android/data/app.countersign.bank/files/feed.wav
 *   adb shell am broadcast -n app.countersign.bank/.spike.FeedAudio
 */
class FeedAudio : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent) {
        val f = File(c.getExternalFilesDir(null), i.getStringExtra("file") ?: "feed.wav")
        if (!f.exists()) {
            Log.w(TAG, "no $f")
            return
        }
        Thread {
            val b = ByteBuffer.wrap(f.readBytes()).order(ByteOrder.LITTLE_ENDIAN)
            b.position(44) // the WAV header
            val pcm = b.asShortBuffer()
            val frame = ShortArray(ListenService.FRAME)
            var sent = 0
            ListenService.feeding = true
            while (pcm.remaining() >= frame.size) {
                pcm.get(frame)
                while (!ListenService.feed(frame.copyOf())) Thread.sleep(5)
                sent++
                Thread.sleep(10) // twice real time
            }
            ListenService.feeding = false
            Log.i(TAG, "fed $sent frames (${sent / 50} s) from ${f.name}")
        }.start()
    }

    companion object {
        private const val TAG = "FeedAudio"
    }
}
