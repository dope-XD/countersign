package app.countersign.bank.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

val Brand = Color(0xFF0B5CAD)
val Ink = Color(0xFF14202B)
val Muted = Color(0xFF5B6B79)
val Paper = Color(0xFFF4F6F8)
val Green = Color(0xFF137A3F)
val GreenSoft = Color(0xFFE3F4E9)
val Amber = Color(0xFF9A5B00)
val AmberSoft = Color(0xFFFFF1D6)
val Red = Color(0xFFB3261E)
val RedSoft = Color(0xFFFCE4E2)

@Composable
fun CsTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = Brand,
            onPrimary = Color.White,
            secondary = Ink,
            background = Paper,
            surface = Color.White,
            onSurface = Ink,
            error = Red,
        ),
        content = content,
    )
}

enum class Tone { Info, Ok, Warn, Danger }

fun Tone.bg() = when (this) {
    Tone.Info -> Color(0xFFE6EEF7)
    Tone.Ok -> GreenSoft
    Tone.Warn -> AmberSoft
    Tone.Danger -> RedSoft
}

fun Tone.fg() = when (this) {
    Tone.Info -> Brand
    Tone.Ok -> Green
    Tone.Warn -> Amber
    Tone.Danger -> Red
}

fun toneOf(s: String?) = when (s) {
    "ok" -> Tone.Ok
    "warn" -> Tone.Warn
    "danger" -> Tone.Danger
    else -> Tone.Info
}

/** A coloured box with one clear message: the main way the app tells people what's going on. */
@Composable
fun Banner(text: String, tone: Tone = Tone.Info, title: String? = null, modifier: Modifier = Modifier) {
    Column(
        modifier
            .fillMaxWidth()
            .background(tone.bg(), RoundedCornerShape(14.dp))
            .padding(14.dp),
    ) {
        if (title != null) Text(title, color = tone.fg(), fontWeight = FontWeight.Bold, fontSize = 17.sp)
        Text(text, color = if (title == null) tone.fg() else Ink, fontSize = 15.sp)
    }
}

@Composable
fun Section(title: String, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Card(
        modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(16.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(title, fontWeight = FontWeight.Bold, fontSize = 18.sp, color = Ink)
            content()
        }
    }
}

/** A round face with initials, for family members. */
@Composable
fun Face(label: String, size: Int = 44, color: Color = Brand) {
    Box(Modifier.size(size.dp).background(color.copy(alpha = 0.12f), CircleShape), contentAlignment = Alignment.Center) {
        Text(label.split(" ").mapNotNull { it.firstOrNull()?.uppercase() }.take(2).joinToString(""), color = color, fontWeight = FontWeight.Bold, fontSize = (size / 2.6).sp)
    }
}

@Composable
fun KeyValue(k: String, v: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(k, color = Muted)
        Text(v, fontWeight = FontWeight.SemiBold)
    }
}
