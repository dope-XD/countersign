package app.countersign.bank

import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class CsApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Prefs.init(this)
        Notify.channels(this)
    }
}

/** What the app remembers: the bank server, and which account this phone is signed in to. */
object Prefs {
    private lateinit var p: SharedPreferences

    fun init(c: Context) {
        p = c.getSharedPreferences("csbank", Context.MODE_PRIVATE)
    }

    var server: String
        get() = p.getString("server", BuildConfig.DEFAULT_SERVER)!!
        set(v) = p.edit().putString("server", v.trim().trimEnd('/')).apply()

    var token: String?
        get() = p.getString("token", null)
        set(v) = p.edit().putString("token", v).apply()

    var customerId: String?
        get() = p.getString("customer", null)
        set(v) = p.edit().putString("customer", v).apply()

    val signedIn: Boolean get() = token != null && customerId != null

    fun signOut() = p.edit().remove("token").remove("customer").apply()
}

/** Events from the bank (approvals, payment results, family requests) for whichever screen is open. */
object Bus {
    val events = MutableSharedFlow<JSONObject>(extraBufferCapacity = 64)
}

class ApiError(message: String, val code: Int) : Exception(message)

/** The engine's app API (engine/mobile.py). Every call carries this phone's device token. */
object Api {
    private val JSON = "application/json".toMediaType()
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    fun request(path: String): Request.Builder {
        val b = Request.Builder().url(Prefs.server + path).header("ngrok-skip-browser-warning", "1")
        Prefs.token?.let { b.header("X-Device-Token", it) }
        return b
    }

    suspend fun get(path: String): JSONObject = run(request(path).get())

    suspend fun post(path: String, body: JSONObject = JSONObject(), headers: Map<String, String> = emptyMap()): JSONObject {
        val b = request(path).post(body.toString().toRequestBody(JSON))
        headers.forEach { (k, v) -> b.header(k, v) }
        return run(b)
    }

    suspend fun delete(path: String): JSONObject = run(request(path).delete())

    suspend fun getArray(path: String): JSONArray = withContext(Dispatchers.IO) {
        http.newCall(request(path).get().build()).execute().use { r ->
            val text = r.body?.string().orEmpty()
            if (!r.isSuccessful) throw ApiError(errorText(text, r.code), r.code)
            JSONArray(text)
        }
    }

    private suspend fun run(b: Request.Builder): JSONObject = withContext(Dispatchers.IO) {
        try {
            http.newCall(b.build()).execute().use { r ->
                val text = r.body?.string().orEmpty()
                if (!r.isSuccessful) throw ApiError(errorText(text, r.code), r.code)
                if (text.isBlank()) JSONObject() else JSONObject(text)
            }
        } catch (e: java.io.IOException) {
            throw ApiError("Can't reach CS Bank. Check your internet connection.", 0)
        }
    }

    /** The engine answers errors as {"error": "..."} or FastAPI's {"detail": "..." | [{"msg": ...}]}. */
    private fun errorText(text: String, code: Int): String = try {
        val o = JSONObject(text)
        when {
            o.has("error") -> o.getString("error")
            o.opt("detail") is JSONArray -> o.getJSONArray("detail").getJSONObject(0).optString("msg").removePrefix("Value error, ")
            o.has("detail") -> o.getString("detail")
            else -> "Something went wrong ($code)."
        }
    } catch (e: Exception) {
        "Something went wrong ($code)."
    }
}

fun JSONObject.str(name: String): String? = if (isNull(name)) null else optString(name)
fun JSONObject.obj(name: String): JSONObject? = if (isNull(name)) null else optJSONObject(name)
fun JSONObject.dbl(name: String): Double? = if (isNull(name)) null else optDouble(name)
fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }

/** ₹2,50,000: Indian digit grouping. */
fun inr(x: Double): String {
    val s = Math.round(x).toString()
    if (s.length <= 3) return "₹$s"
    var head = s.dropLast(3)
    val parts = mutableListOf<String>()
    while (head.length > 2) {
        parts.add(0, head.takeLast(2))
        head = head.dropLast(2)
    }
    if (head.isNotEmpty()) parts.add(0, head)
    return "₹" + parts.joinToString(",") + "," + s.takeLast(3)
}
