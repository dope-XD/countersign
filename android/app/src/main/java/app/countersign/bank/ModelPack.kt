package app.countersign.bank

import android.content.Context
import android.util.Log
import app.countersign.bank.data.ModelState
import app.countersign.bank.data.ModelStatus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.withContext
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipInputStream

/**
 * The one model pack (CONTRACT.md, `GET /api/m/models`): speech-to-text (Hindi-capable + English), Silero VAD, the
 * voice-clone model and the conversation models, downloaded once into the app's private files and checked against its sha256.
 * `pack.json` inside says which file is which (see ml/pack_models.py).
 */
object ModelPack {
    private const val TAG = "ModelPack"
    private val _state = MutableStateFlow(ModelState(ModelStatus.MISSING, 0f, 0))
    val state: StateFlow<ModelState> = _state

    fun dir(c: Context) = File(c.filesDir, "models")

    /** pack.json of the installed pack, or null. */
    fun manifest(c: Context): JSONObject? = File(dir(c), "pack.json").takeIf { it.exists() }?.let { runCatching { JSONObject(it.readText()) }.getOrNull() }

    fun refresh(c: Context) {
        val m = manifest(c)
        // a pack without the conversation models (v1) still works in basic mode, but is offered again as a download
        if (m != null && m.has("conv")) _state.value = ModelState(ModelStatus.READY, 1f, m.optInt("size_mb"))
        else if (_state.value.status != ModelStatus.DOWNLOADING) _state.value = ModelState(ModelStatus.MISSING, 0f, _state.value.sizeMb)
    }

    /** Asks the relay which pack to fetch, downloads it with progress, checks it and unpacks it. */
    suspend fun download(c: Context) = withContext(Dispatchers.IO) {
        if (_state.value.status == ModelStatus.DOWNLOADING) return@withContext
        try {
            val list = Api.getArray("/api/m/models")
            val pack = list.getJSONObject(0)
            val size = pack.optInt("size_mb")
            _state.value = ModelState(ModelStatus.DOWNLOADING, 0f, size)
            val tmp = File(c.cacheDir, "pack.zip")
            val sha = MessageDigest.getInstance("SHA-256")
            Api.http.newCall(Request.Builder().url(pack.getString("url")).build()).execute().use { r ->
                check(r.isSuccessful) { "download failed (${r.code})" }
                val body = r.body ?: error("empty download")
                val total = body.contentLength().takeIf { it > 0 } ?: (size * 1_000_000L)
                var done = 0L
                body.byteStream().use { input ->
                    tmp.outputStream().use { out ->
                        val buf = ByteArray(1 shl 16)
                        while (true) {
                            val n = input.read(buf)
                            if (n < 0) break
                            out.write(buf, 0, n)
                            sha.update(buf, 0, n)
                            done += n
                            _state.value = ModelState(ModelStatus.DOWNLOADING, (done.toFloat() / total).coerceIn(0f, 0.99f), size)
                        }
                    }
                }
            }
            val got = sha.digest().joinToString("") { "%02x".format(it) }
            val want = pack.optString("sha256")
            check(want.isEmpty() || want == got) { "the download was damaged" }
            val target = dir(c)
            val fresh = File(c.filesDir, "models.new").apply { deleteRecursively(); mkdirs() }
            ZipInputStream(tmp.inputStream().buffered()).use { z ->
                while (true) {
                    val e = z.nextEntry ?: break
                    val f = File(fresh, e.name.substringAfterLast('/'))
                    if (!e.isDirectory) f.outputStream().use { z.copyTo(it) }
                }
            }
            tmp.delete()
            check(File(fresh, "pack.json").exists()) { "the pack has no pack.json" }
            target.deleteRecursively()
            fresh.renameTo(target)
            Speech.reset()
            VoiceCheck.reset()
            ConversationModels.reset()
            _state.value = ModelState(ModelStatus.READY, 1f, size)
            Log.i(TAG, "model pack ready (${size} MB)")
        } catch (e: Exception) {
            Log.w(TAG, "model pack not downloaded: $e")
            _state.value = ModelState(ModelStatus.FAILED, 0f, _state.value.sizeMb)
            throw ApiError(c.getString(R.string.models_failed), 0)
        }
    }
}
