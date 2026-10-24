package app.countersign.bank.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.data.Verdict
import app.countersign.bank.ui.Green
import app.countersign.bank.ui.GreenSoft
import app.countersign.bank.ui.Grey
import app.countersign.bank.ui.GreySoft
import app.countersign.bank.ui.Red
import app.countersign.bank.ui.RedSoft

/** Which of the three looks a verdict gets: ✓ green, ✗ red, or grey (? or a spinner while checking). */
private enum class Look(val fg: Color, val bg: Color) { YES(Green, GreenSoft), MAYBE(Green, Color.White), NO(Red, RedSoft), UNKNOWN(Grey, GreySoft), WAIT(Grey, GreySoft) }

private fun Verdict.look() = when (this) {
    Verdict.CHECKING -> Look.WAIT
    Verdict.VERIFIED -> Look.YES
    Verdict.LIKELY -> Look.MAYBE
    Verdict.NOT_WITH_YOU, Verdict.NOT_THEM -> Look.NO
    Verdict.CANT_REACH -> Look.UNKNOWN
}

/** "Really Rahul", "Not Rahul's phone", "Couldn't check": the words for [verdict] about the member called [label]. */
@Composable
fun verdictWords(verdict: Verdict, label: String): String = when (verdict) {
    Verdict.CHECKING -> stringResource(R.string.verdict_checking, label)
    Verdict.VERIFIED -> stringResource(R.string.verdict_verified, label)
    Verdict.LIKELY -> stringResource(R.string.verdict_likely, label)
    Verdict.NOT_WITH_YOU, Verdict.NOT_THEM -> stringResource(R.string.verdict_not_them, label)
    Verdict.CANT_REACH -> stringResource(R.string.verdict_cant_reach)
}

/**
 * A verdict as icon + words + colour, so it reads without colour too. [label] is what this phone calls the member.
 * [spoofSuspected] adds "Caller ID may be faked" under it. The icons are decorative: the words say the same thing,
 * and the chip is read out as one item when it changes.
 */
@Composable
fun VerdictChip(verdict: Verdict, label: String, modifier: Modifier = Modifier, spoofSuspected: Boolean = false) {
    val look = verdict.look()
    val shape = RoundedCornerShape(12.dp)
    Column(
        modifier
            .border(2.dp, look.fg, shape)
            .background(look.bg, shape)
            .padding(horizontal = 14.dp, vertical = 8.dp)
            .defaultMinSize(minHeight = 32.dp)
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            when (look) {
                Look.YES, Look.MAYBE -> Icon(Icons.Filled.Check, contentDescription = null, tint = look.fg, modifier = Modifier.size(26.dp))
                Look.NO -> Icon(Icons.Filled.Close, contentDescription = null, tint = look.fg, modifier = Modifier.size(26.dp))
                Look.UNKNOWN -> QuestionMark(look.fg)
                Look.WAIT -> CircularProgressIndicator(Modifier.size(22.dp), color = look.fg, strokeWidth = 3.dp)
            }
            Text(verdictWords(verdict, label), color = look.fg, style = MaterialTheme.typography.titleSmall)
        }
        if (spoofSuspected) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Filled.Warning, contentDescription = null, tint = Red, modifier = Modifier.size(22.dp))
                Text(stringResource(R.string.verdict_spoof), color = Red, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

/** A "?" in a circle, the grey "couldn't check" mark (the core icon set has no question mark). */
@Composable
private fun QuestionMark(colour: Color) {
    Box(Modifier.size(26.dp).background(colour, CircleShape), contentAlignment = Alignment.Center) {
        val size = with(LocalDensity.current) { 18.dp.toSp() }
        Text("?", color = Color.White, fontWeight = FontWeight.Bold, fontSize = size, lineHeight = size)
    }
}

@PreviewLanguages
@Composable
private fun VerdictChipPreview() = PreviewBox {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Verdict.entries.forEach { VerdictChip(it, "Rahul") }
        VerdictChip(Verdict.NOT_THEM, "Rahul", spoofSuspected = true)
    }
}
