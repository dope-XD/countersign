package app.countersign.bank.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.data.Check
import app.countersign.bank.data.FakeRepository
import app.countersign.bank.data.Repository
import app.countersign.bank.data.RingState
import app.countersign.bank.data.Scenario
import app.countersign.bank.ui.components.SubScreen

/** History: the last 10 family checks, newest first: the verdict, who, when, and whether their phone was rung. */
@Composable
fun HistoryScreen(repo: Repository, onBack: () -> Unit) {
    val home by repo.home.collectAsState()
    HistoryContent(home?.checks.orEmpty(), onBack)
}

@Composable
internal fun HistoryContent(checks: List<Check>, onBack: () -> Unit) = SubScreen(stringResource(R.string.history_title), onBack) {
    if (checks.isEmpty()) {
        Text(stringResource(R.string.home_no_checks), color = Muted, style = MaterialTheme.typography.bodyLarge)
        return@SubScreen
    }
    Column(Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(16.dp)).padding(vertical = 4.dp)) {
        checks.take(10).forEach { c ->
            CheckRow(c)
            Text(
                stringResource(if (c.ring == RingState.NONE) R.string.history_rang_no else R.string.history_rang_yes),
                Modifier.padding(start = 66.dp, bottom = 8.dp),
                color = Muted,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

private fun sampleChecks(): List<Check> = FakeRepository(Scenario.IDLE).home.value!!.checks

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun HistoryPreview() = CsTheme { HistoryContent(sampleChecks(), {}) }
