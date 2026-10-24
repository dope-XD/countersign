package app.countersign.bank.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.ui.Brand
import app.countersign.bank.ui.ButtonHeight
import app.countersign.bank.ui.Green
import app.countersign.bank.ui.Ink
import app.countersign.bank.ui.Line
import app.countersign.bank.ui.Red

enum class ButtonKind { Primary, Yes, No, Quiet }

/**
 * The app's one button: full width, at least 56 dp tall, 20 sp words.
 * [ButtonKind.Yes] and [ButtonKind.No] are the green and red answers; [ButtonKind.Quiet] is a white outlined button.
 */
@Composable
fun BigButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    kind: ButtonKind = ButtonKind.Primary,
    icon: ImageVector? = null,
    enabled: Boolean = true,
) {
    val m = modifier.fillMaxWidth().defaultMinSize(minHeight = ButtonHeight)
    val shape = RoundedCornerShape(14.dp)
    val label: @Composable () -> Unit = {
        if (icon != null) {
            Icon(icon, contentDescription = null, Modifier.size(26.dp))
            Spacer(Modifier.width(10.dp))
        }
        Text(text, style = MaterialTheme.typography.labelLarge, textAlign = TextAlign.Center)
    }
    if (kind == ButtonKind.Quiet) {
        OutlinedButton(
            onClick, m, enabled = enabled, shape = shape,
            border = BorderStroke(2.dp, Line),
            colors = ButtonDefaults.outlinedButtonColors(containerColor = Color.White, contentColor = Ink),
        ) { label() }
    } else {
        val fill = when (kind) {
            ButtonKind.Yes -> Green
            ButtonKind.No -> Red
            else -> Brand
        }
        Button(
            onClick, m, enabled = enabled, shape = shape,
            colors = ButtonDefaults.buttonColors(containerColor = fill, contentColor = Color.White),
        ) { label() }
    }
}

@PreviewLanguages
@Composable
private fun BigButtonPreview() = PreviewBox {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        BigButton(stringResource(R.string.action_call), {}, icon = Icons.Filled.Call)
        BigButton(stringResource(R.string.action_yes_its_me), {}, kind = ButtonKind.Yes, icon = Icons.Filled.Check)
        BigButton(stringResource(R.string.action_no_not_me), {}, kind = ButtonKind.No, icon = Icons.Filled.Close)
        BigButton(stringResource(R.string.action_skip), {}, kind = ButtonKind.Quiet)
    }
}
