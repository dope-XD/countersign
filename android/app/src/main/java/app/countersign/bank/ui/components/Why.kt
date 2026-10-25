package app.countersign.bank.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import app.countersign.bank.R

/** A cue or context id (scam_patterns.json, CONTRACT.md "Context signal ids") in plain words, or null for ids we don't show. */
fun cueWords(id: String): Int? = when (id) {
    "authority" -> R.string.why_authority
    "threat" -> R.string.why_threat
    "secrecy" -> R.string.why_secrecy
    "video_move" -> R.string.why_video_move
    "money_ask" -> R.string.why_money_ask
    "credentials" -> R.string.why_credentials
    "remote_access" -> R.string.why_remote_access
    "urgency" -> R.string.why_urgency
    "family_emergency" -> R.string.why_family_emergency
    "reward" -> R.string.why_reward
    "verification_pretext" -> R.string.why_verification_pretext
    "parcel_customs" -> R.string.why_parcel_customs
    "sim_block" -> R.string.why_sim_block
    "job_task" -> R.string.why_job_task
    "investment" -> R.string.why_investment
    "boss_pretext" -> R.string.why_boss_pretext
    "payment_redirect" -> R.string.why_payment_redirect
    "remote_app_opened" -> R.string.why_remote_app_opened
    "caller_check_failed" -> R.string.why_caller_check_failed
    "video_call_unknown" -> R.string.why_video_call_unknown
    "international_number" -> R.string.why_international_number
    "long_call" -> R.string.why_long_call
    "synthetic_voice" -> R.string.why_synthetic_voice
    "victim_says" -> R.string.why_victim_says
    "digits_read_out" -> R.string.why_digits_read_out
    "bank_claim_not_1600" -> R.string.why_bank_claim_not_1600
    else -> null
}

/** "Why: police or a court · a threat · keep it secret" — at most [max] reasons, in the phone's language. */
@Composable
fun whyLine(cues: List<String>, max: Int = 3): String? {
    val words = cues.mapNotNull(::cueWords).distinct().take(max).map { stringResource(it) }
    return if (words.isEmpty()) null else stringResource(R.string.why_prefix, words.joinToString(" · "))
}
