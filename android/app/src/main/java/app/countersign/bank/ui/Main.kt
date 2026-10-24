package app.countersign.bank.ui

import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountCircle
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.fragment.app.FragmentActivity
import app.countersign.bank.Api
import app.countersign.bank.ApiError
import app.countersign.bank.Approval
import app.countersign.bank.ApprovalActivity
import app.countersign.bank.Approvals
import app.countersign.bank.BuildConfig
import app.countersign.bank.Bus
import app.countersign.bank.Home
import app.countersign.bank.MainActivity
import app.countersign.bank.Payment
import app.countersign.bank.Prefs
import app.countersign.bank.data.FakeRepository
import app.countersign.bank.data.Repo
import app.countersign.bank.data.Scenario
import app.countersign.bank.ui.components.familyColours
import app.countersign.bank.inr
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

enum class Tab(val label: String, val icon: ImageVector) {
    Home("Home", Icons.Filled.Home),
    Pay("Pay", Icons.AutoMirrored.Filled.Send),
    Family("Family", Icons.Filled.Favorite),
    Profile("Profile", Icons.Filled.AccountCircle),
}

/** The account as the bank last told us, reloaded on every bank event and every 8 s while open. */
class HomeModel {
    var home by mutableStateOf<Home?>(null)
    var error by mutableStateOf<String?>(null)
    var signedOut by mutableStateOf(false)

    suspend fun load() {
        try {
            home = Home.from(Api.get("/api/m/home"))
            error = null
        } catch (e: ApiError) {
            if (e.code == 401) signedOut = true else error = e.message
        }
    }
}

@Composable
fun AppRoot(activity: MainActivity) {
    // a fresh debug install on fake data starts as a new user, so setup can be tried end to end
    val repo = remember {
        Repo.instance.also { if (BuildConfig.DEBUG && !Language.chosen(activity)) (it as? FakeRepository)?.play(Scenario.NEW_USER) }
    }
    val signedIn by repo.signedIn.collectAsState()
    // set up already when the app opens signed in; otherwise setup runs to its end, permissions included
    var setUp by remember { mutableStateOf(repo.signedIn.value && Language.chosen(activity)) }
    if (!signedIn || !setUp) {
        SetupFlow(repo) { setUp = true }
        return
    }

    // Home, and one level below it: "add", "settings", "check", "history", "member:<id>"
    var screen by rememberSaveable { mutableStateOf("home") }
    val home by repo.home.collectAsState()
    val scope = rememberCoroutineScope()
    val goHome = { screen = "home" }
    // a scanned csbank://family link opens Add family with the code filled in
    LaunchedEffect(activity.inviteCode) { if (activity.inviteCode != null) screen = "add" }
    BackHandler(screen != "home", goHome)

    when {
        screen == "add" -> AddFamilyScreen(repo, activity.inviteCode) {
            activity.inviteCode = null
            goHome()
        }
        screen == "settings" -> SettingsScreen(repo, goHome)
        screen == "check" -> CheckScreen(repo, goHome)
        screen == "history" -> HistoryScreen(repo, goHome)
        screen.startsWith("member:") -> {
            val family = home?.family.orEmpty()
            val member = family.firstOrNull { it.id == screen.removePrefix("member:") }
            if (member == null) {
                LaunchedEffect(Unit) { goHome() }
            } else {
                MemberScreen(member, familyColours(family).getValue(member.id), onRemove = {
                    scope.launch { runCatching { repo.removeMember(member.id) } }
                    goHome()
                }, onBack = goHome)
            }
        }
        else -> HomeScreen(repo, onAddFamily = { screen = "add" }, onMember = { screen = "member:$it" }, onSettings = { screen = "settings" }, onHistory = { screen = "history" }, onCheck = { screen = "check" })
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainShell(activity: MainActivity, signOut: () -> Unit) {
    val model = remember { HomeModel() }
    var tab by remember { mutableStateOf(if (activity.inviteCode != null) Tab.Family else Tab.Home) }
    var openPayment by remember { mutableStateOf<Payment?>(null) }
    var calling by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        launch { Bus.events.collect { model.load() } }
        while (true) {
            model.load()
            delay(8000)
        }
    }
    LaunchedEffect(activity.inviteCode) { if (activity.inviteCode != null) tab = Tab.Family }
    if (model.signedOut) {
        Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center) {
            Banner("This phone's account isn't on the bank server any more (it may have been reset). Sign up again.", Tone.Warn)
            Spacer(Modifier.height(16.dp))
            Button(signOut, modifier = Modifier.fillMaxWidth()) { Text("Sign up again") }
        }
        return
    }

    val pay = openPayment
    if (calling) {
        CallScreen(activity, model) { calling = false }
        return
    }
    if (pay != null) {
        PaymentSheet(activity, pay, model) { openPayment = null }
        return
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("CS Bank", fontWeight = FontWeight.ExtraBold, color = Brand) },
                actions = {
                    Button({ calling = true }, modifier = Modifier.padding(end = 8.dp), colors = ButtonDefaults.buttonColors(containerColor = Green)) {
                        Icon(Icons.Filled.Call, null)
                        Spacer(Modifier.width(6.dp))
                        Text("Call CS Bank")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Paper),
            )
        },
        bottomBar = {
            NavigationBar(containerColor = Color.White) {
                Tab.entries.forEach { t ->
                    NavigationBarItem(selected = tab == t, onClick = { tab = t }, icon = { Icon(t.icon, null) }, label = { Text(t.label) })
                }
            }
        },
        containerColor = Paper,
    ) { pad ->
        Box(Modifier.padding(pad)) {
            when (tab) {
                Tab.Home -> HomeScreen(activity, model) { openPayment = it }
                Tab.Pay -> PayForm(model) { openPayment = it }
                Tab.Family -> FamilyScreen(activity, model)
                Tab.Profile -> ProfileScreen(model, signOut)
            }
        }
    }
}

@Composable
fun HomeScreen(activity: FragmentActivity, model: HomeModel, open: (Payment) -> Unit) {
    val h = model.home
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        model.error?.let { item { Banner(it, Tone.Warn) } }
        if (h == null) {
            item { Text("Loading…", color = Muted) }
            return@LazyColumn
        }
        val a = h.account
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Brand), shape = RoundedCornerShape(20.dp), modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(20.dp)) {
                    Text("Hi, ${a.firstName}", color = Color.White.copy(alpha = 0.85f))
                    Text(inr(a.balance), color = Color.White, fontSize = 34.sp, fontWeight = FontWeight.ExtraBold)
                    Text("${a.upi}  ·  A/c …${a.accountNo.takeLast(4)}", color = Color.White.copy(alpha = 0.85f), fontSize = 14.sp)
                }
            }
        }
        item {
            val call = h.bankCall
            if (call != null) {
                Banner("You're on a verified call with ${call.optString("with")}.", Tone.Ok, title = "This is really CS Bank")
            } else {
                Banner("CS Bank is not calling you right now. If someone on a call says they're from CS Bank, hang up and call us from this app.", Tone.Info)
            }
        }
        if (a.killSwitch != null) {
            item { KillSwitchCard(activity, model) }
        }
        items(h.approvals, key = { it.id }) { ApprovalCard(activity, it, model) }
        h.payments.filter { it.open }.forEach { p ->
            item(key = p.id) {
                Card(Modifier.fillMaxWidth().clickable { open(p) }, colors = CardDefaults.cardColors(containerColor = AmberSoft)) {
                    Column(Modifier.padding(16.dp)) {
                        Text("${p.amountText} to ${p.payee}", fontWeight = FontWeight.Bold)
                        Text(
                            when (p.status) {
                                "held" -> "On hold for an hour. Tap to cancel."
                                "awaiting_family" -> "Waiting for family to answer."
                                else -> "Paused. Tap to choose what to do."
                            },
                            color = Amber,
                        )
                    }
                }
            }
        }
        item {
            Section("Recent payments") {
                val done = h.payments.filter { !it.open }
                if (done.isEmpty()) Text("No payments yet.", color = Muted)
                done.take(8).forEach { p ->
                    Row(Modifier.fillMaxWidth().clickable { open(p) }, horizontalArrangement = Arrangement.SpaceBetween) {
                        Column(Modifier.weight(1f)) {
                            Text(p.redirectedTo?.optString("upi_id") ?: p.payee, fontWeight = FontWeight.SemiBold)
                            Text(statusText(p.status), color = if (p.status == "cancelled") Red else Muted, fontSize = 13.sp)
                        }
                        Text(p.amountText, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
        if (a.killSwitch == null) item { KillSwitchCard(activity, model) }
    }
}

fun statusText(s: String) = when (s) {
    "executed" -> "Sent"
    "cancelled" -> "Stopped"
    "held" -> "On hold"
    "paused", "confirm" -> "Paused"
    "awaiting_family" -> "Checking with family"
    else -> s
}

/** A pending family check or bank approval, answered right here (the full-screen ring opens the same thing). */
@Composable
fun ApprovalCard(activity: FragmentActivity, a: Approval, model: HomeModel) {
    val scope = rememberCoroutineScope()
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    Card(colors = CardDefaults.cardColors(containerColor = Color.White), shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(if (a.isFamily) "FAMILY CHECK" else if (a.kind == "kill_switch_off") "KILL SWITCH" else "CS BANK APPROVAL", color = Brand, fontWeight = FontWeight.Bold, fontSize = 12.sp)
            Text(a.question, fontWeight = FontWeight.Bold, fontSize = 19.sp)
            Text(a.detail, color = Muted)
            error?.let { Banner(it, Tone.Danger) }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton({
                    busy = true
                    scope.launch {
                        error = Approvals.decide(activity, a, approve = false)
                        busy = false
                        model.load()
                    }
                }, enabled = !busy, modifier = Modifier.weight(1f)) { Text(if (a.isFamily) "No, not me" else "No") }
                Button({
                    busy = true
                    scope.launch {
                        error = Approvals.decide(activity, a, approve = true)
                        busy = false
                        model.load()
                    }
                }, enabled = !busy, modifier = Modifier.weight(1f)) { Text(if (a.isFamily) "Yes, it was me" else "Yes") }
            }
            OutlinedButton({
                activity.startActivity(Intent(activity, ApprovalActivity::class.java).putExtra(ApprovalActivity.EXTRA_ID, a.id))
            }, modifier = Modifier.fillMaxWidth()) { Text("Open full screen") }
        }
    }
}

/** RBI's proposed "kill switch": block every payment and account change at once, for when something feels wrong. */
@Composable
fun KillSwitchCard(activity: FragmentActivity, model: HomeModel) {
    val scope = rememberCoroutineScope()
    val ks = model.home?.account?.killSwitch
    var error by remember { mutableStateOf<String?>(null) }
    var confirm by remember { mutableStateOf(false) }
    Section(if (ks == null) "Something feels wrong?" else "Kill switch is ON") {
        if (ks == null) {
            Text("Block all payments and account changes in one tap. Turning it back on takes your fingerprint and an hour.", color = Muted)
            if (confirm) {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton({ confirm = false }, Modifier.weight(1f)) { Text("Not now") }
                    Button({
                        scope.launch {
                            try {
                                Api.post("/api/m/kill-switch")
                            } catch (e: ApiError) {
                                error = e.message
                            }
                            confirm = false
                            model.load()
                        }
                    }, Modifier.weight(1f), colors = ButtonDefaults.buttonColors(containerColor = Red)) { Text("Block everything") }
                }
            } else {
                Button({ confirm = true }, Modifier.fillMaxWidth(), colors = ButtonDefaults.buttonColors(containerColor = Red)) { Text("Block all payments") }
            }
        } else {
            val offAt = ks.optDouble("off_at", 0.0)
            if (offAt > 0) {
                Banner("Payments will work again at ${clockAt(offAt)}.", Tone.Warn)
            } else {
                Text("No payments or account changes can happen, even if someone has your details or your voice.", color = Muted)
                OutlinedButton({
                    scope.launch {
                        try {
                            Api.post("/api/m/kill-switch/off")
                        } catch (e: ApiError) {
                            error = e.message
                        }
                        model.load()
                    }
                }, Modifier.fillMaxWidth()) { Text("Turn it off (fingerprint, then 1 hour)") }
            }
        }
        error?.let { Banner(it, Tone.Danger) }
    }
}

fun clockAt(epochSeconds: Double): String =
    java.text.SimpleDateFormat("h:mm a", java.util.Locale.getDefault()).format(java.util.Date((epochSeconds * 1000).toLong()))

@Composable
fun Centered(content: @Composable () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { content() }
}
