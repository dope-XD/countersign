package app.countersign.bank

import android.content.Context
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import java.nio.ByteOrder

/** "Check a recording": any audio file Android can play (mp3, m4a, ogg, wav, amr…) → 16 kHz mono floats, in memory. */
object AudioFile {
    private const val MAX_SECONDS = 600

    fun decode16k(c: Context, uri: Uri): FloatArray {
        val ex = MediaExtractor()
        try {
            ex.setDataSource(c, uri, null)
            val track = (0 until ex.trackCount).firstOrNull { ex.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("audio/") == true }
                ?: throw ApiError(c.getString(R.string.check_not_audio), 0)
            ex.selectTrack(track)
            val fmt = ex.getTrackFormat(track)
            val mime = fmt.getString(MediaFormat.KEY_MIME)!!
            var rate = fmt.getInteger(MediaFormat.KEY_SAMPLE_RATE)
            var channels = fmt.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
            val codec = MediaCodec.createDecoderByType(mime)
            codec.configure(fmt, null, null, 0)
            codec.start()
            val pcm = ArrayList<Float>(rate * 30)
            val info = MediaCodec.BufferInfo()
            var inputDone = false
            var outputDone = false
            while (!outputDone) {
                if (!inputDone) {
                    val i = codec.dequeueInputBuffer(10_000)
                    if (i >= 0) {
                        val n = ex.readSampleData(codec.getInputBuffer(i)!!, 0)
                        if (n < 0) {
                            codec.queueInputBuffer(i, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                            inputDone = true
                        } else {
                            codec.queueInputBuffer(i, 0, n, ex.sampleTime, 0)
                            ex.advance()
                        }
                    }
                }
                val o = codec.dequeueOutputBuffer(info, 10_000)
                if (o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    codec.outputFormat.let {
                        rate = it.getInteger(MediaFormat.KEY_SAMPLE_RATE)
                        channels = it.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
                    }
                } else if (o >= 0) {
                    val buf = codec.getOutputBuffer(o)!!.order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
                    val frames = buf.remaining() / channels
                    for (f in 0 until frames) {
                        var s = 0f
                        for (ch in 0 until channels) s += buf.get(f * channels + ch) / 32768f
                        pcm.add(s / channels)
                    }
                    codec.releaseOutputBuffer(o, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) outputDone = true
                    if (pcm.size > rate * MAX_SECONDS) outputDone = true
                }
            }
            codec.stop()
            codec.release()
            return resample(pcm.toFloatArray(), rate, 16_000)
        } catch (e: ApiError) {
            throw e
        } catch (e: Exception) {
            throw ApiError(c.getString(R.string.check_not_audio), 0)
        } finally {
            ex.release()
        }
    }

    /** Linear resampling; speech-to-text doesn't need better. */
    fun resample(x: FloatArray, from: Int, to: Int): FloatArray {
        if (from == to || x.isEmpty()) return x
        val n = (x.size.toLong() * to / from).toInt()
        val step = from.toDouble() / to
        return FloatArray(n) { i ->
            val p = i * step
            val k = p.toInt().coerceAtMost(x.size - 1)
            val fr = (p - k).toFloat()
            if (k + 1 < x.size) x[k] * (1 - fr) + x[k + 1] * fr else x[k]
        }
    }
}
