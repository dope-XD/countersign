package app.countersign.bank

import android.app.KeyguardManager
import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import android.util.Base64
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import kotlinx.coroutines.suspendCancellableCoroutine
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * This phone's key, made in the Android Keystore at sign-up. The private half never leaves the
 * phone's secure hardware and only signs after a fingerprint or screen-lock check, so "Yes, it
 * was me" can only come from this phone in its owner's hands. The bank keeps the public half.
 */
object DeviceKey {
    private const val ALIAS = "csbank_device_key"

    class Cancelled(message: String) : Exception(message)

    private fun store(): KeyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    fun exists(): Boolean = store().containsAlias(ALIAS)

    /** A key needs a screen lock (PIN, pattern, password or fingerprint) to protect it. */
    fun screenLockSet(c: Context): Boolean = c.getSystemService(KeyguardManager::class.java).isDeviceSecure

    /** Makes a fresh key and returns its public half (X.509 SubjectPublicKeyInfo, base64). */
    fun create(): String {
        if (exists()) store().deleteEntry(ALIAS)
        fun spec(strongBox: Boolean) = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .setUserAuthenticationRequired(true)
            .setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG or KeyProperties.AUTH_DEVICE_CREDENTIAL)
            .setInvalidatedByBiometricEnrollment(false)
            .setIsStrongBoxBacked(strongBox)
            .build()
        val gen = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore")
        try {
            gen.initialize(spec(true))
            gen.generateKeyPair()
        } catch (e: StrongBoxUnavailableException) {
            gen.initialize(spec(false)) // no separate security chip: the phone's trusted environment instead
            gen.generateKeyPair()
        }
        return publicKey()
    }

    fun publicKey(): String = Base64.encodeToString(store().getCertificate(ALIAS).publicKey.encoded, Base64.NO_WRAP)

    fun delete() {
        if (exists()) store().deleteEntry(ALIAS)
    }

    /** Asks for the fingerprint or screen lock, then signs `message`. Base64 DER ECDSA signature. */
    suspend fun sign(activity: FragmentActivity, message: String, title: String, subtitle: String): String {
        val sig = Signature.getInstance("SHA256withECDSA")
        sig.initSign(store().getKey(ALIAS, null) as PrivateKey)
        return suspendCancellableCoroutine { cont ->
            val prompt = BiometricPrompt(activity, ContextCompat.getMainExecutor(activity), object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    try {
                        val s = result.cryptoObject!!.signature!!
                        s.update(message.toByteArray(Charsets.UTF_8))
                        cont.resume(Base64.encodeToString(s.sign(), Base64.NO_WRAP))
                    } catch (e: Exception) {
                        cont.resumeWithException(e)
                    }
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    if (cont.isActive) cont.resumeWithException(Cancelled(errString.toString()))
                }
            })
            val info = BiometricPrompt.PromptInfo.Builder()
                .setTitle(title)
                .setSubtitle(subtitle)
                .setAllowedAuthenticators(BIOMETRIC_STRONG or DEVICE_CREDENTIAL)
                .build()
            prompt.authenticate(info, BiometricPrompt.CryptoObject(sig))
            cont.invokeOnCancellation { prompt.cancelAuthentication() }
        }
    }

    /** What the bank checks: the phone signed "approve:<approval id>:<challenge>". */
    fun approvalMessage(approval: Approval) = "approve:${approval.id}:${approval.challenge}"
}
