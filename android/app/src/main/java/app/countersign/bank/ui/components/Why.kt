package app.countersign.bank.ui.components

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
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
    "direct_ask" -> R.string.why_direct_ask
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

/**
 * Every scam call follows the same four steps: who they claim to be, the trouble (or the offer), the pressure, and
 * what they want. The card shows which steps this call has made so far, so it reads as a pattern, not a word list.
 */
enum class ScamStep(@StringRes val title: Int, val ids: List<String>) {
    WHO(R.string.step_who, listOf("caller_check_failed", "authority", "boss_pretext", "bank_claim_not_1600", "international_number", "video_call_unknown")),
    TROUBLE(R.string.step_trouble, listOf("threat", "family_emergency", "parcel_customs", "sim_block", "verification_pretext", "reward", "investment", "job_task")),
    PRESSURE(R.string.step_pressure, listOf("secrecy", "urgency", "video_move", "long_call")),
    WANT(R.string.step_want, listOf("direct_ask", "money_ask", "credentials", "remote_access", "payment_redirect", "remote_app_opened", "victim_says", "digits_read_out")),
}

/** For each step, the first of the call's cues that shows it (in the step's own order of strength), or null. */
fun scamStory(cues: List<String>): List<Pair<ScamStep, String?>> = ScamStep.entries.map { step -> step to step.ids.firstOrNull { it in cues } }

/** The four steps, ✓ with the reason in plain words for the steps this call has made, a grey "…" for the rest. */
@Composable
fun ScamStory(cues: List<String>, tick: Color, ink: Color, muted: Color) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        scamStory(cues).forEach { (step, id) ->
            Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (id != null) {
                    Icon(Icons.Filled.Check, contentDescription = null, tint = tick, modifier = Modifier.size(20.dp))
                } else {
                    Text("…", color = muted, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.size(20.dp))
                }
                val words = id?.let { cueWords(it) }?.let { stringResource(it) }
                Text(
                    stringResource(step.title) + if (words != null) ": $words" else "",
                    color = if (id != null) ink else muted,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = if (id != null) FontWeight.Medium else FontWeight.Normal,
                )
            }
        }
    }
}
