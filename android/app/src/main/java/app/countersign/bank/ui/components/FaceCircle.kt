package app.countersign.bank.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.data.Member
import app.countersign.bank.ui.Green
import app.countersign.bank.ui.Grey
import app.countersign.bank.ui.Ink

// Initials in the colour on a soft tint of it: at least 5:1 for each. No greens or reds, so a face never looks like a verdict.
private val FaceColours = listOf(
    Color(0xFF0B5CAD), // blue
    Color(0xFF7B3FA0), // purple
    Color(0xFF9C3A5E), // rose
    Color(0xFF7D5200), // ochre
    Color(0xFF006B5F), // teal
    Color(0xFF3949AB), // indigo
)

/** The same person always gets the same colour, on every phone: pick by a stable id (member id, or the name). */
fun faceColour(key: String): Color = FaceColours[Math.floorMod(key.hashCode(), FaceColours.size)]

/** "Rahul Sharma" → "RS", "Mummy" → "M", "राहुल" → "र". */
fun initials(name: String): String =
    name.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.take(2)
        .joinToString("") { word -> String(Character.toChars(word.codePointAt(0))).uppercase() }

/**
 * A round face with initials on a soft per-person colour.
 * [online] adds a dot (green when online, grey when not); leave it null to show no dot.
 */
@Composable
fun FaceCircle(name: String, modifier: Modifier = Modifier, key: String = name, size: Dp = 64.dp, online: Boolean? = null) {
    val status = when (online) {
        true -> stringResource(R.string.face_online)
        false -> stringResource(R.string.face_offline)
        null -> null
    }
    val colour = faceColour(key)
    Box(modifier.size(size).clearAndSetSemantics { contentDescription = listOfNotNull(name, status).joinToString(", ") }) {
        Box(Modifier.size(size).background(colour.copy(alpha = 0.16f), CircleShape), contentAlignment = Alignment.Center) {
            // sized to the circle, not the font setting, so large fonts don't spill out of it
            val letters = with(LocalDensity.current) { (size * 0.4f).toSp() }
            Text(initials(name), color = colour, fontWeight = FontWeight.Bold, fontSize = letters)
        }
        if (online != null) {
            Box(
                Modifier
                    .align(Alignment.BottomEnd)
                    .size(size * 0.28f)
                    .border(3.dp, Color.White, CircleShape)
                    .background(if (online) Green else Grey, CircleShape),
            )
        }
    }
}

/** A family member as Home shows them: the face with its online dot, and what I call them underneath. */
@Composable
fun MemberFace(member: Member, modifier: Modifier = Modifier, size: Dp = 72.dp) {
    Column(modifier.width(size + 24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        FaceCircle(member.label, key = member.id, size = size, online = member.online)
        Text(
            member.label,
            color = Ink,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.clearAndSetSemantics { },
        )
    }
}

@PreviewLanguages
@Composable
private fun FaceCirclePreview() = PreviewBox {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        MemberFace(Member("c_rahul", "Rahul", "Rahul Sharma", "", 0, online = true, newLink = false))
        MemberFace(Member("c_mom", "Mummy", "Sunita Sharma", "", 0, online = false, newLink = false))
        MemberFace(Member("c_priya", "प्रिया", "Priya", "", 0, online = true, newLink = false))
    }
}
