package com.melonmail.app.ui

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.ContactsContract
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Forward
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.Reply
import androidx.compose.material.icons.automirrored.filled.ReplyAll
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Contacts
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.TextButton
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.FileProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.google.firebase.messaging.FirebaseMessaging
import com.melonmail.app.NavTarget
import com.melonmail.app.BuildConfig
import com.melonmail.app.R
import com.melonmail.app.data.Address
import com.melonmail.app.data.Api
import com.melonmail.app.data.AttachmentInfo
import com.melonmail.app.data.Envelope
import com.melonmail.app.data.MsgBody
import com.melonmail.app.data.PinnedMail
import com.melonmail.app.data.TokenRegister
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import java.io.File
import kotlin.math.abs

// ---------------------------------------------------------------------------
// 导航
// ---------------------------------------------------------------------------

@Composable
fun AppRoot(navTarget: MutableState<NavTarget?>) {
    val vm: MailViewModel = viewModel()
    val context = LocalContext.current

    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { }
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            permLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    val nav = rememberNavController()
    NavHost(navController = nav, startDestination = "unified") {
        composable("unified") { UnifiedScreen(vm, nav) }
        composable("accounts") { AccountsScreen(vm, nav) }
        composable("settings") { SettingsScreen(vm, nav) }
        composable(
            "inbox/{account}",
            arguments = listOf(navArgument("account") { type = NavType.StringType }),
        ) { e ->
            InboxScreen(vm, e.arguments?.getString("account").orEmpty(), nav)
        }
        composable(
            "message/{account}/{id}?folder={folder}",
            arguments = listOf(
                navArgument("account") { type = NavType.StringType },
                navArgument("id") { type = NavType.StringType },
                navArgument("folder") { type = NavType.StringType; defaultValue = "INBOX" },
            ),
        ) { e ->
            MessageScreen(
                vm,
                e.arguments?.getString("account").orEmpty(),
                e.arguments?.getString("id").orEmpty(),
                e.arguments?.getString("folder") ?: "INBOX",
                nav,
            )
        }
        composable(
            "compose/{account}",
            arguments = listOf(navArgument("account") { type = NavType.StringType }),
        ) { e ->
            ComposeScreen(vm, e.arguments?.getString("account").orEmpty(), null, false, null, "INBOX", nav)
        }
        composable(
            "reply/{account}/{id}/{all}?folder={folder}",
            arguments = listOf(
                navArgument("account") { type = NavType.StringType },
                navArgument("id") { type = NavType.StringType },
                navArgument("all") { type = NavType.BoolType },
                navArgument("folder") { type = NavType.StringType; defaultValue = "INBOX" },
            ),
        ) { e ->
            ComposeScreen(
                vm,
                e.arguments?.getString("account").orEmpty(),
                e.arguments?.getString("id").orEmpty(),
                e.arguments?.getBoolean("all") ?: false,
                null,
                e.arguments?.getString("folder") ?: "INBOX",
                nav,
            )
        }
        composable(
            "forward/{account}/{id}?folder={folder}",
            arguments = listOf(
                navArgument("account") { type = NavType.StringType },
                navArgument("id") { type = NavType.StringType },
                navArgument("folder") { type = NavType.StringType; defaultValue = "INBOX" },
            ),
        ) { e ->
            ComposeScreen(
                vm,
                e.arguments?.getString("account").orEmpty(),
                null,
                false,
                e.arguments?.getString("id").orEmpty(),
                e.arguments?.getString("folder") ?: "INBOX",
                nav,
            )
        }
    }

    // 通知点击 → 跳到对应账号收件箱,再进具体邮件(冷启动/后台都生效)。
    LaunchedEffect(navTarget.value) {
        val target = navTarget.value ?: return@LaunchedEffect
        navTarget.value = null
        nav.navigate("inbox/${target.account}")
        if (!target.messageId.isNullOrBlank()) {
            nav.navigate("message/${target.account}/${target.messageId}")
        }
    }

    // 在根页(unified,返回本会退出 app)时:连按两次返回才彻底关闭;其他页正常返回。
    val currentRoute = nav.currentBackStackEntryAsState().value?.destination?.route
    var lastBack by remember { mutableStateOf(0L) }
    BackHandler(enabled = currentRoute == "unified") {
        val now = System.currentTimeMillis()
        if (now - lastBack < 2000) {
            (context as? Activity)?.finishAndRemoveTask()  // 彻底关闭 + 从最近任务移除
        } else {
            lastBack = now
            Toast.makeText(context, "再按一次退出", Toast.LENGTH_SHORT).show()
        }
    }
}

private fun NavHostController.switchTab(route: String) {
    navigate(route) {
        popUpTo("unified") { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}

@Composable
private fun MelonBottomBar(
    nav: NavHostController,
    current: String,
    onReselectUnified: () -> Unit = {},  // 已在统一页时再次点「统一」(双击)触发,用于回顶
) {
    var lastUnifiedTap by remember { mutableStateOf(0L) }
    NavigationBar {
        NavigationBarItem(
            selected = current == "unified",
            onClick = {
                if (current != "unified") {
                    nav.switchTab("unified")
                } else {
                    val now = System.currentTimeMillis()
                    if (now - lastUnifiedTap < 350) onReselectUnified()  // 350ms 内第二击 = 双击
                    lastUnifiedTap = now
                }
            },
            icon = { Icon(Icons.Default.Inbox, null) },
            label = { Text("统一") },
        )
        NavigationBarItem(
            selected = current == "accounts",
            onClick = { if (current != "accounts") nav.switchTab("accounts") },
            icon = { Icon(Icons.Default.Email, null) },
            label = { Text("账户") },
        )
        NavigationBarItem(
            selected = current == "settings",
            onClick = { if (current != "settings") nav.switchTab("settings") },
            icon = { Icon(Icons.Default.Settings, null) },
            label = { Text("设置") },
        )
    }
}

// ---------------------------------------------------------------------------
// 统一收件箱(跨账号)
// ---------------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UnifiedScreen(vm: MailViewModel, nav: NavHostController) {
    val baseUrl by vm.settings.baseUrl.collectAsState(initial = "")
    LaunchedEffect(baseUrl) { if (baseUrl.isNotBlank()) { vm.loadUnified(); vm.loadUnread() } }
    var query by remember { mutableStateOf("") }
    var pendingDelete by remember { mutableStateOf<Pair<String, String>?>(null) }  // (account, id)
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val shown = if (query.isBlank()) vm.unified else vm.unified.filter {
        it.envelope.sender.contains(query, true) ||
            it.envelope.subject.contains(query, true) ||
            it.account.contains(query, true)
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = {
                    val unread = vm.unreadTotal
                    Text(if (unread > 0) "统一收件箱 · $unread 未读" else "统一收件箱")
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        bottomBar = {
            MelonBottomBar(nav, "unified", onReselectUnified = {
                scope.launch { listState.animateScrollToItem(0) }
            })
        },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            if (baseUrl.isBlank()) {
                ConfigHint { nav.switchTab("settings") }
                return@Column
            }
            SearchField(query) { query = it }
            vm.unifiedError?.let { ErrorText(it) }
            PullToRefreshBox(
                isRefreshing = vm.unifiedLoading,
                onRefresh = { vm.loadUnified(force = true); vm.loadUnread() },
                modifier = Modifier.fillMaxSize(),
            ) {
                // 置顶区(跨账号,仅非搜索时);普通列表去掉已置顶的避免重复。
                val pinned = if (query.isBlank()) vm.unifiedPins() else emptyList()
                val pinnedKeys = pinned.mapTo(HashSet()) { it.account to it.envelope.id }
                val regular = shown.filterNot { (it.account to it.envelope.id) in pinnedKeys }
                LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
                    if (pinned.isNotEmpty()) {
                        item { PinnedSectionLabel() }
                        items(pinned, key = { "pin-${it.account}/${it.envelope.id}" }) { pm ->
                            SwipeableMailRow(
                                onPin = { vm.togglePin(pm.account, pm.folder, pm.envelope) },
                                onDelete = { pendingDelete = pm.account to pm.envelope.id },
                            ) {
                                UnifiedRow(AccountEnvelope(pm.account, pm.envelope), pinned = true) {
                                    nav.navigate("message/${pm.account}/${pm.envelope.id}")
                                }
                            }
                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        }
                        item { Spacer(Modifier.height(6.dp)) }
                    }
                    items(regular, key = { "${it.account}/${it.envelope.id}" }) { item ->
                        SwipeableMailRow(
                            onPin = { vm.togglePin(item.account, INBOX, item.envelope) },
                            onDelete = { pendingDelete = item.account to item.envelope.id },
                        ) {
                            UnifiedRow(item) { nav.navigate("message/${item.account}/${item.envelope.id}") }
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                    if (vm.unifiedLoadingMore) item { LoadingFooter() }
                }
            }
        }
    }

    LoadMoreEffect(listState, enabled = vm.unifiedHasMore && !vm.unifiedLoadingMore && query.isBlank()) {
        vm.loadMoreUnified()
    }

    pendingDelete?.let { (acc, delId) ->
        ConfirmDeleteDialog(
            onConfirm = { vm.deleteMessage(acc, delId); pendingDelete = null },
            onDismiss = { pendingDelete = null },
        )
    }
}

@Composable
private fun UnifiedRow(item: AccountEnvelope, pinned: Boolean = false, onClick: () -> Unit) {
    val env = item.envelope
    val unread = env.isUnread
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(
            Modifier.align(Alignment.CenterVertically).size(8.dp).clip(CircleShape)
                .background(if (unread) MaterialTheme.colorScheme.primary else Color.Transparent),
        )
        Spacer(Modifier.width(8.dp))
        Avatar(env.sender)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(item.account, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.weight(1f))
                if (pinned) {
                    Icon(Icons.Default.PushPin, "已置顶", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(14.dp))
                    Spacer(Modifier.width(4.dp))
                }
                env.date?.let { Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
            Text(env.sender, fontWeight = if (unread) FontWeight.Bold else FontWeight.Normal, maxLines = 1)
            Text(
                env.subjectOrNone,
                color = if (unread) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant,
                fontWeight = if (unread) FontWeight.SemiBold else FontWeight.Normal,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 2,
            )
        }
    }
}

// ---------------------------------------------------------------------------
// 账户列表
// ---------------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AccountsScreen(vm: MailViewModel, nav: NavHostController) {
    val baseUrl by vm.settings.baseUrl.collectAsState(initial = "")
    LaunchedEffect(baseUrl) { if (baseUrl.isNotBlank()) { vm.loadAccounts(); vm.loadUnread() } }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("账户") },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        bottomBar = { MelonBottomBar(nav, "accounts") },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize().padding(horizontal = 16.dp)) {
            Text("专注连接,邮件随行", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(12.dp))
            if (baseUrl.isBlank()) {
                ConfigHint { nav.switchTab("settings") }
                return@Column
            }
            vm.accountsError?.let { ErrorText(it) }
            if (vm.accountsLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
            LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                items(vm.accounts, key = { it }) { acc ->
                    AccountCard(acc, vm.unreadCounts[acc] ?: 0) { nav.navigate("inbox/$acc") }
                }
            }
        }
    }
}

@Composable
private fun AccountCard(account: String, unread: Int = 0, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(18.dp),
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = 1.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Avatar(account)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(account, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.titleMedium)
                Text(
                    if (unread > 0) "$unread 封未读" else "点按查看收件箱",
                    color = if (unread > 0) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (unread > 0) {
                UnreadBadge(unread)
                Spacer(Modifier.width(8.dp))
            }
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun UnreadBadge(count: Int) {
    Box(
        Modifier
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.primary)
            .defaultMinSize(minWidth = 22.dp, minHeight = 22.dp)
            .padding(horizontal = 7.dp, vertical = 2.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            if (count > 99) "99+" else "$count",
            color = MaterialTheme.colorScheme.onPrimary,
            style = MaterialTheme.typography.labelMedium,
        )
    }
}

// ---------------------------------------------------------------------------
// 单账号收件箱(下拉刷新 + 上拉加载)
// ---------------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InboxScreen(vm: MailViewModel, account: String, nav: NavHostController) {
    LaunchedEffect(account) { vm.loadFolders(account) }
    var folder by remember(account) { mutableStateOf(INBOX) }
    LaunchedEffect(account, folder) { vm.loadInbox(account, folder) }
    val sentFolder = vm.sentFolderOf(account)
    val isSent = folder != INBOX
    var query by remember { mutableStateOf("") }
    var pendingDelete by remember { mutableStateOf<String?>(null) }
    val listState = rememberLazyListState()
    val shown = if (query.isBlank()) vm.inbox else vm.inbox.filter {
        it.sender.contains(query, true) || it.subject.contains(query, true) ||
            (it.recipient?.display?.contains(query, true) ?: false)
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text(account) },
                navigationIcon = {
                    IconButton(onClick = { nav.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { vm.refreshInbox() }) {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = { nav.navigate("compose/$account") },
                containerColor = MaterialTheme.colorScheme.primary,
                contentColor = MaterialTheme.colorScheme.onPrimary,
            ) { Icon(Icons.Default.Edit, contentDescription = "写信") }
        },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            SearchField(query) { query = it }
            // 仅当探测到「已发」文件夹时显示切换;否则只有收件箱。
            if (sentFolder != null) {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    FolderChip("收件箱", selected = !isSent) { folder = INBOX }
                    FolderChip("已发", selected = isSent) { folder = sentFolder }
                }
            }
            vm.inboxError?.let { ErrorText(it) }
            PullToRefreshBox(
                isRefreshing = vm.inboxLoading,
                onRefresh = { vm.refreshInbox() },
                modifier = Modifier.fillMaxSize(),
            ) {
                // 置顶区(仅非搜索时显示),普通列表去掉已置顶的避免重复。
                val pinned = if (query.isBlank()) vm.pinsFor(account, folder) else emptyList()
                val pinnedIds = pinned.mapTo(HashSet()) { it.envelope.id }
                val regular = shown.filterNot { it.id in pinnedIds }
                LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
                    if (pinned.isNotEmpty()) {
                        item { PinnedSectionLabel() }
                        items(pinned, key = { "pin-${it.envelope.id}" }) { pm ->
                            SwipeableMailRow(
                                onPin = { vm.togglePin(account, folder, pm.envelope) },   // 已置顶 → 取消
                                onDelete = { pendingDelete = pm.envelope.id },
                            ) {
                                InboxRow(pm.envelope, isSent, pinned = true) {
                                    nav.navigate("message/$account/${pm.envelope.id}?folder=${Uri.encode(folder)}")
                                }
                            }
                            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        }
                        item { Spacer(Modifier.height(6.dp)) }
                    }
                    items(regular, key = { it.id }) { env ->
                        SwipeableMailRow(
                            onPin = { vm.togglePin(account, folder, env) },
                            onDelete = { pendingDelete = env.id },
                        ) {
                            InboxRow(env, isSent) {
                                nav.navigate("message/$account/${env.id}?folder=${Uri.encode(folder)}")
                            }
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                    if (vm.inboxLoadingMore) item { LoadingFooter() }
                }
            }
        }
    }

    LoadMoreEffect(listState, enabled = vm.inboxHasMore && !vm.inboxLoadingMore && query.isBlank()) {
        vm.loadMoreInbox()
    }

    pendingDelete?.let { delId ->
        ConfirmDeleteDialog(
            onConfirm = { vm.deleteMessage(account, delId, folder); pendingDelete = null },
            onDismiss = { pendingDelete = null },
        )
    }
}

@Composable
private fun FolderChip(label: String, selected: Boolean, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(16.dp),
        color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant,
        contentColor = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant,
    ) {
        Text(label, Modifier.padding(horizontal = 16.dp, vertical = 6.dp), style = MaterialTheme.typography.labelLarge)
    }
}

/** 列表行通用滑动:右划=置顶/取消置顶,左划=删除。两者都回弹,只触发动作。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SwipeableMailRow(
    onPin: () -> Unit,
    onDelete: () -> Unit,
    content: @Composable () -> Unit,
) {
    val state = rememberSwipeToDismissBoxState(
        confirmValueChange = { v ->
            when (v) {
                SwipeToDismissBoxValue.StartToEnd -> onPin()
                SwipeToDismissBoxValue.EndToStart -> onDelete()
                SwipeToDismissBoxValue.Settled -> {}
            }
            false
        },
    )
    SwipeToDismissBox(
        state = state,
        backgroundContent = {
            when (state.dismissDirection) {
                SwipeToDismissBoxValue.StartToEnd -> SwipeBg(
                    Alignment.CenterStart, MaterialTheme.colorScheme.primaryContainer,
                    Icons.Default.PushPin, "置顶", MaterialTheme.colorScheme.onPrimaryContainer,
                )
                SwipeToDismissBoxValue.EndToStart -> SwipeBg(
                    Alignment.CenterEnd, MaterialTheme.colorScheme.errorContainer,
                    Icons.Default.Delete, "删除", MaterialTheme.colorScheme.onErrorContainer,
                )
                else -> {}
            }
        },
    ) {
        Surface(color = MaterialTheme.colorScheme.background) { content() }
    }
}

@Composable
private fun SwipeBg(
    align: Alignment,
    color: Color,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    desc: String,
    tint: Color,
) {
    Box(
        Modifier.fillMaxSize().background(color).padding(horizontal = 24.dp),
        contentAlignment = align,
    ) {
        Icon(icon, contentDescription = desc, tint = tint)
    }
}

/** 置顶区与普通列表之间的分隔标签。 */
@Composable
private fun PinnedSectionLabel() {
    Row(
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Default.PushPin, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(14.dp))
        Spacer(Modifier.width(4.dp))
        Text("置顶", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
    }
}

@Composable
private fun ConfirmDeleteDialog(onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("删除邮件") },
        text = { Text("确定删除这封邮件?(移到回收站)") },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text("删除", color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

@Composable
private fun InboxRow(env: Envelope, sent: Boolean = false, pinned: Boolean = false, onClick: () -> Unit) {
    val unread = env.isUnread
    // 已发箱里展示收件人(发给谁),收件箱展示发件人。
    val who = if (sent) {
        env.recipient?.display?.takeIf { it.isNotBlank() }?.let { "发给 $it" } ?: "(无收件人)"
    } else {
        env.sender
    }
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(
            Modifier.align(Alignment.CenterVertically).size(8.dp).clip(CircleShape)
                .background(if (unread && !sent) MaterialTheme.colorScheme.primary else Color.Transparent),
        )
        Spacer(Modifier.width(8.dp))
        Avatar(if (sent) (env.recipient?.display ?: "?") else env.sender)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    who,
                    fontWeight = if (unread && !sent) FontWeight.Bold else FontWeight.Normal,
                    modifier = Modifier.weight(1f),
                    maxLines = 1,
                )
                if (pinned) {
                    Icon(Icons.Default.PushPin, "已置顶", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(14.dp))
                    Spacer(Modifier.width(4.dp))
                }
                env.date?.let { Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
            Spacer(Modifier.height(2.dp))
            Text(
                env.subjectOrNone,
                color = if (unread) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant,
                fontWeight = if (unread) FontWeight.SemiBold else FontWeight.Normal,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 2,
            )
        }
    }
}

// ---------------------------------------------------------------------------
// 邮件详情
// ---------------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MessageScreen(vm: MailViewModel, account: String, id: String, folder: String, nav: NavHostController) {
    // 确保该账号对应文件夹已加载——从通知深链进入时,inbox 页面从未真正组合过,其 loadInbox
    // 不会触发,导致 envelopeById 找不到这封 → 标题/发件人空白。这里主动加载(已加载则 no-op)。
    LaunchedEffect(account, folder) { vm.loadInbox(account, folder) }
    // 后台+新鲜度跳过时,刚到的新信可能不在已加载列表里(头部会空)。等当前加载结束后,
    // 若仍找不到这封,就强制刷一次把它补进来;只试一次,防死循环。
    var triedHeaderRefresh by remember(account, id) { mutableStateOf(false) }
    LaunchedEffect(account, id, vm.inbox, vm.inboxLoading) {
        if (!triedHeaderRefresh && !vm.inboxLoading &&
            vm.inboxAccount == account && vm.envelopeById(id) == null
        ) {
            triedHeaderRefresh = true
            vm.loadInbox(account, folder, force = true)
        }
    }
    val isSent = folder != INBOX
    // 不要 remember:随 vm.inbox 变化自动刷新(数据到位后标题/发件人就显示出来)。
    val env = vm.envelopeById(id)
    val dark = isSystemInDarkTheme()
    var showDelete by remember { mutableStateOf(false) }
    val result by produceState<Result<MsgBody>?>(initialValue = null, account, id, folder) {
        value = vm.loadMessage(account, id, folder)
    }
    if (showDelete) {
        ConfirmDeleteDialog(
            onConfirm = { showDelete = false; vm.deleteMessage(account, id, folder); nav.popBackStack() },
            onDismiss = { showDelete = false },
        )
    }
    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("邮件") },
                navigationIcon = {
                    IconButton(onClick = { nav.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { showDelete = true }) {
                        Icon(Icons.Default.Delete, contentDescription = "删除", tint = MaterialTheme.colorScheme.error)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        bottomBar = {
            Surface(color = MaterialTheme.colorScheme.surface, shadowElevation = 8.dp) {
                Row(Modifier.fillMaxWidth().padding(12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val fEnc = Uri.encode(folder)
                    OutlinedButton(onClick = { nav.navigate("reply/$account/$id/false?folder=$fEnc") }, modifier = Modifier.weight(1f), contentPadding = PaddingValues(horizontal = 6.dp)) {
                        Icon(Icons.AutoMirrored.Filled.Reply, contentDescription = null)
                        Spacer(Modifier.width(4.dp)); Text("回复")
                    }
                    OutlinedButton(onClick = { nav.navigate("reply/$account/$id/true?folder=$fEnc") }, modifier = Modifier.weight(1f), contentPadding = PaddingValues(horizontal = 6.dp)) {
                        Icon(Icons.AutoMirrored.Filled.ReplyAll, contentDescription = null)
                        Spacer(Modifier.width(4.dp)); Text("全部")
                    }
                    OutlinedButton(onClick = { nav.navigate("forward/$account/$id?folder=$fEnc") }, modifier = Modifier.weight(1f), contentPadding = PaddingValues(horizontal = 6.dp)) {
                        Icon(Icons.AutoMirrored.Filled.Forward, contentDescription = null)
                        Spacer(Modifier.width(4.dp)); Text("转发")
                    }
                }
            }
        },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            // 固定头部(不随正文滚动)
            Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp)) {
                Text(env?.subjectOrNone ?: "(邮件)", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(14.dp))
                var headerExpanded by remember { mutableStateOf(false) }
                Column(Modifier.fillMaxWidth().clickable { headerExpanded = !headerExpanded }) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Avatar(env?.sender ?: "?")
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            // 已发箱:主名显示收件人,副标题标明这是自己发出的。
                            val primary = if (isSent) (env?.recipient?.display?.takeIf { it.isNotBlank() } ?: "(收件人)") else (env?.sender ?: "(未知发件人)")
                            Text(primary, fontWeight = FontWeight.SemiBold)
                            Text(if (isSent) "由 $account 发出" else "发给 我 · $account", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                        }
                        env?.date?.let { Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        Icon(
                            if (headerExpanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                            contentDescription = "展开",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (headerExpanded) {
                        Spacer(Modifier.height(8.dp))
                        SelectionContainer {
                            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                Text("发件人:${addressFull(env?.from)}", style = MaterialTheme.typography.bodySmall)
                                Text("收件人:${addressFull(env?.recipient)}", style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
                Spacer(Modifier.height(12.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                // 附件(每封都查,有才显示)
                AttachmentsSection(vm, account, id, folder)
                Spacer(Modifier.height(4.dp))
            }
            // 正文区:占剩余空间,WebView/纯文本各自内部滚动
            val r = result
            when {
                r == null -> Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
                r.isFailure -> Text(
                    "加载失败: ${r.exceptionOrNull()?.message}",
                    Modifier.padding(16.dp).weight(1f),
                    color = MaterialTheme.colorScheme.error,
                )
                else -> {
                    val body = r.getOrThrow()
                    if (body.html.isNotBlank()) {
                        Column(Modifier.fillMaxWidth().weight(1f)) {
                            var showImages by remember(id) { mutableStateOf(false) }
                            if (!showImages) {
                                Surface(
                                    color = MaterialTheme.colorScheme.surfaceVariant,
                                    modifier = Modifier.fillMaxWidth().clickable { showImages = true },
                                ) {
                                    Row(
                                        Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Icon(Icons.Default.Image, null, tint = MaterialTheme.colorScheme.primary)
                                        Spacer(Modifier.width(8.dp))
                                        Text("已隐藏远程图片(防跟踪)— 点此显示", style = MaterialTheme.typography.bodySmall)
                                    }
                                }
                            }
                            // 用 Box 承载 weight,AndroidView 用 fillMaxSize 拿到确定约束。
                            // 直接给 AndroidView 加 weight 时,WebView 内部滚动会被重测成高度 0 → 正文变空白。
                            Box(Modifier.fillMaxWidth().weight(1f)) {
                                EmailWebView(body.html, showImages, dark, Modifier.fillMaxSize())
                            }
                        }
                    } else {
                        SelectionContainer(
                            Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()),
                        ) {
                            Text(
                                body.text.ifBlank { "(无正文)" },
                                Modifier.padding(16.dp),
                                style = MaterialTheme.typography.bodyMedium,
                            )
                        }
                    }
                }
            }
        }
    }
}

// 暗色:强制深底 + 用 !important 把文字/背景都覆盖(覆盖邮件内联颜色,避免深字深底看不见)。
private const val DARK_CSS =
    "<style>html,body{background:#15171c!important;color:#e6e8eb!important;margin:0;padding:12px;}" +
        "*{background-color:transparent!important;background-image:none!important;color:#e6e8eb!important;border-color:#3a3f47!important;}" +
        "a{color:#8ab4f8!important;}img{max-width:100%!important;height:auto!important;}</style>"

/** 用 WebView 渲染 HTML 正文。showImages=false 时禁远程图片;dark 时注入暗色 CSS 跟随系统主题。 */
@Composable
private fun EmailWebView(html: String, showImages: Boolean, dark: Boolean, modifier: Modifier) {
    val context = LocalContext.current
    val lastKey = remember { mutableStateOf<Triple<String, Boolean, Boolean>?>(null) }
    AndroidView(
        modifier = modifier,
        factory = { ctx ->
            WebView(ctx).apply {
                settings.javaScriptEnabled = false
                settings.useWideViewPort = true
                settings.loadWithOverviewMode = true
                settings.builtInZoomControls = true
                settings.displayZoomControls = false
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                        runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, request.url)) }
                        return true
                    }
                }
            }
        },
        update = { web ->
            val key = Triple(html, showImages, dark)
            if (lastKey.value != key) {  // 只在内容/开关/主题变化时重载,避免每次重组闪烁
                web.settings.blockNetworkImage = !showImages
                web.settings.loadsImagesAutomatically = showImages
                web.setBackgroundColor(if (dark) 0xFF15171C.toInt() else 0xFFFFFFFF.toInt())
                val content = if (dark) DARK_CSS + html else html
                web.loadDataWithBaseURL(null, content, "text/html", "UTF-8", null)
                lastKey.value = key
            }
        },
    )
}

@Composable
private fun AttachmentsSection(vm: MailViewModel, account: String, id: String, folder: String) {
    val list by produceState<List<AttachmentInfo>?>(initialValue = null, account, id, folder) {
        value = vm.listAttachments(account, id, folder).getOrDefault(emptyList())
    }
    val items = list
    if (items.isNullOrEmpty()) return  // 加载中或无附件 → 不显示附件区
    var expanded by remember(id) { mutableStateOf(false) }  // 默认折叠,把空间留给正文
    Spacer(Modifier.height(12.dp))
    Row(
        Modifier.fillMaxWidth().clickable { expanded = !expanded },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Default.AttachFile, null, tint = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.width(6.dp))
        Text("附件(${items.size})", fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        Icon(
            if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
            contentDescription = if (expanded) "收起附件" else "展开附件",
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
    if (expanded) {
        Spacer(Modifier.height(8.dp))
        // 限定最大高度 + 内部滚动:附件再多也不会撑爆头部、把正文(WebView)挤成 0 高度变空白。
        Column(
            Modifier.heightIn(max = 240.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items.forEach { ReceivedAttachmentChip(vm, account, id, folder, it) }
        }
    }
}

@Composable
private fun ReceivedAttachmentChip(vm: MailViewModel, account: String, id: String, folder: String, info: AttachmentInfo) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    var pendingFile by remember { mutableStateOf<File?>(null) }

    // 系统"保存到…"选择器(可存到 下载/Files/Drive,免存储权限)。
    val saver = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("*/*")) { uri ->
        val f = pendingFile
        pendingFile = null
        if (uri != null && f != null) {
            runCatching {
                context.contentResolver.openOutputStream(uri)?.use { out -> f.inputStream().use { it.copyTo(out) } }
            }
        }
    }

    Surface(
        onClick = {  // 点整行 = 下载并用其他 app 打开
            if (!busy) {
                busy = true
                scope.launch {
                    val f = vm.downloadAttachment(account, id, info.name, folder).getOrNull()
                    busy = false
                    if (f != null) openFile(context, f)
                }
            }
        },
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(start = 12.dp, top = 4.dp, bottom = 4.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Default.AttachFile, null, tint = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(info.name, maxLines = 1)
                Text(humanSize(info.size), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (busy) {
                CircularProgressIndicator(Modifier.size(20.dp))
            } else {
                IconButton(onClick = {  // 保存到设备
                    busy = true
                    scope.launch {
                        val f = vm.downloadAttachment(account, id, info.name, folder).getOrNull()
                        busy = false
                        if (f != null) {
                            pendingFile = f
                            saver.launch(info.name)
                        }
                    }
                }) {
                    Icon(Icons.Default.Download, contentDescription = "保存", tint = MaterialTheme.colorScheme.primary)
                }
            }
        }
    }
}

private fun openFile(context: Context, file: File) {
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
    val mime = context.contentResolver.getType(uri) ?: "*/*"
    val intent = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(uri, mime)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    runCatching { context.startActivity(Intent.createChooser(intent, "打开附件")) }
}

private fun addressFull(a: Address?): String {
    if (a == null) return "(无)"
    val name = a.name?.takeIf { it.isNotBlank() }
    val addr = a.addr?.takeIf { it.isNotBlank() }
    return when {
        name != null && addr != null -> "$name <$addr>"
        addr != null -> addr
        name != null -> name
        else -> "(无)"
    }
}

private fun pickContactEmail(context: Context, uri: Uri): String? =
    context.contentResolver.query(
        uri,
        arrayOf(ContactsContract.CommonDataKinds.Email.ADDRESS),
        null, null, null,
    )?.use { c -> if (c.moveToFirst()) c.getString(0) else null }

private fun humanSize(bytes: Long): String = when {
    bytes >= 1_048_576 -> "%.1f MB".format(bytes / 1_048_576.0)
    bytes >= 1024 -> "%.0f KB".format(bytes / 1024.0)
    else -> "$bytes B"
}

// ---------------------------------------------------------------------------
// 回复 / 撰写
// ---------------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ComposeScreen(
    vm: MailViewModel,
    account: String,
    replyToId: String?,
    replyAll: Boolean,
    forwardId: String?,
    folder: String,
    nav: NavHostController,
) {
    val scope = rememberCoroutineScope()
    val isReply = replyToId != null
    val isForward = forwardId != null
    val needTo = !isReply             // 新撰写 + 转发都要填收件人
    val needSubject = !isReply && !isForward  // 仅新撰写填主题(转发主题由服务端 Fwd: 生成)
    var to by remember { mutableStateOf("") }
    var subject by remember { mutableStateOf("") }
    var body by remember { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var attachments by remember { mutableStateOf<List<AttachmentDraft>>(emptyList()) }

    val context = LocalContext.current
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        attachments = attachments + uris.map { AttachmentDraft(it, vm.displayName(it)) }
    }
    val contactPicker = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val uri = result.data?.data
        if (result.resultCode == Activity.RESULT_OK && uri != null) {
            pickContactEmail(context, uri)?.let { email ->
                to = if (to.isBlank()) email else to.trimEnd().trimEnd(',').trim() + ", " + email
            }
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        when {
                            isReply -> if (replyAll) "回复全部" else "回复"
                            isForward -> "转发"
                            else -> "撰写邮件"
                        },
                    )
                },
                navigationIcon = {
                    IconButton(onClick = { nav.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { picker.launch(arrayOf("*/*")) }) {
                        Icon(Icons.Default.AttachFile, contentDescription = "添加附件")
                    }
                    IconButton(
                        enabled = !sending,
                        onClick = {
                            sending = true; errorMsg = null
                            scope.launch {
                                val res = when {
                                    isReply -> vm.reply(account, replyToId!!, body, replyAll, attachments.map { it.uri }, folder)
                                    isForward -> vm.forward(account, forwardId!!, to, body, attachments.map { it.uri }, folder)
                                    else -> vm.send(account, to, subject, body, attachments.map { it.uri })
                                }
                                sending = false
                                res.fold(onSuccess = { nav.popBackStack() }, onFailure = { errorMsg = it.message })
                            }
                        },
                    ) {
                        Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "发送", tint = MaterialTheme.colorScheme.primary)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
    ) { pad ->
        Column(Modifier.padding(pad).padding(16.dp).fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("账号: $account", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (needTo) {
                OutlinedTextField(
                    to, { to = it },
                    label = { Text("收件人(逗号分隔)") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    trailingIcon = {
                        IconButton(onClick = {
                            contactPicker.launch(Intent(Intent.ACTION_PICK, ContactsContract.CommonDataKinds.Email.CONTENT_URI))
                        }) { Icon(Icons.Default.Contacts, contentDescription = "选择联系人") }
                    },
                )
            }
            if (needSubject) {
                OutlinedTextField(subject, { subject = it }, label = { Text("主题") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
            }
            attachments.forEach { att ->
                DraftAttachmentChip(att.name) { attachments = attachments - att }
            }
            OutlinedTextField(body, { body = it }, label = { Text(if (isReply) "回复内容" else "正文") }, modifier = Modifier.fillMaxWidth().weight(1f))
            if (sending) LinearProgressIndicator(Modifier.fillMaxWidth())
            errorMsg?.let { Text("发送失败: $it", color = MaterialTheme.colorScheme.error) }
        }
    }
}

private data class AttachmentDraft(val uri: Uri, val name: String)

@Composable
private fun DraftAttachmentChip(name: String, onRemove: () -> Unit) {
    Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.surfaceVariant, modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Default.AttachFile, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.width(8.dp))
            Text(name, modifier = Modifier.weight(1f), maxLines = 1)
            IconButton(onClick = onRemove) { Icon(Icons.Default.Close, contentDescription = "移除") }
        }
    }
}

// ---------------------------------------------------------------------------
// 设置(底部 tab)
// ---------------------------------------------------------------------------

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun SettingsScreen(vm: MailViewModel, nav: NavHostController) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val savedBase by vm.settings.baseUrl.collectAsState(initial = "")
    val savedToken by vm.settings.apiToken.collectAsState(initial = "")
    val fcm by vm.settings.fcmToken.collectAsState(initial = "")

    // 服务器版本(连上才有);随地址/Token 变化重取。
    val serverVersion by produceState<String?>(initialValue = null, savedBase, savedToken) {
        value = if (savedBase.isNotBlank() && savedToken.isNotBlank()) vm.fetchServerVersion() else null
    }
    // 长按二维码 → 用系统「保存到…」存图(免存储权限)。
    val qrSaver = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("image/jpeg")) { uri ->
        if (uri != null) runCatching {
            val bmp = BitmapFactory.decodeResource(context.resources, R.drawable.payme)
            context.contentResolver.openOutputStream(uri)?.use { out -> bmp.compress(Bitmap.CompressFormat.JPEG, 95, out) }
        }
    }

    var base by remember(savedBase) { mutableStateOf(savedBase) }
    var token by remember(savedToken) { mutableStateOf(savedToken) }
    var showToken by remember { mutableStateOf(false) }
    var saved by remember { mutableStateOf(false) }
    var pushStatus by remember { mutableStateOf<String?>(null) }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("设置") },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
        },
        bottomBar = { MelonBottomBar(nav, "settings") },
    ) { pad ->
        Column(
            Modifier.padding(pad).padding(16.dp).fillMaxSize().verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            SectionHeader("服务器")
            SettingsCard {
                OutlinedTextField(base, { base = it; saved = false }, label = { Text("服务器地址 (https://…)") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    token, { token = it; saved = false },
                    label = { Text("API Token") },
                    modifier = Modifier.fillMaxWidth(), singleLine = true,
                    visualTransformation = if (showToken) VisualTransformation.None else PasswordVisualTransformation(),
                    trailingIcon = {
                        TextButton(onClick = { showToken = !showToken }) {
                            Text(if (showToken) "隐藏" else "显示")
                        }
                    },
                )
                Spacer(Modifier.height(12.dp))
                Button(onClick = {
                    scope.launch {
                        vm.settings.setBaseUrl(base)
                        vm.settings.setApiToken(token)
                        saved = true
                        vm.loadAccounts()
                    }
                }) { Text("保存") }
                if (saved) {
                    Spacer(Modifier.height(6.dp))
                    Text("已保存", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodySmall)
                }
            }

            SectionHeader("推送")
            SettingsCard {
                Text("推送注册", fontWeight = FontWeight.SemiBold)
                Text(
                    "填好上面的服务器地址和 Token 后,本机会自动注册接收推送(多设备),无需手动操作。若收不到推送,可点下面按钮重试。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    if (fcm.isBlank()) "状态:尚未获取到 FCM token(检查 google-services.json)" else "状态:已获取 FCM token",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedButton(onClick = { reRegister(scope, vm) { pushStatus = it } }) { Text("重新上报到服务器") }
                pushStatus?.let {
                    Spacer(Modifier.height(6.dp))
                    Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
                }
            }

            SectionHeader("版本")
            SettingsCard {
                VersionRow("App 版本", BuildConfig.VERSION_NAME)
                Spacer(Modifier.height(8.dp))
                VersionRow(
                    "服务器版本",
                    when {
                        savedBase.isBlank() -> "未配置"
                        serverVersion != null -> serverVersion!!
                        else -> "连接中…"
                    },
                )
            }

            SectionHeader("关于")
            SettingsCard {
                Text("Melon Mail 🍉", fontWeight = FontWeight.SemiBold)
                Text(
                    "自建邮件推送 + 收发系统:服务器盯着多个 IMAP 邮箱,新邮件经 FCM 推送到手机;" +
                        "手机不存任何邮箱凭据,省电。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    "GitHub:github.com/bidabrain/mailpush",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.clickable {
                        runCatching {
                            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/bidabrain/mailpush")))
                        }
                    },
                )
                Spacer(Modifier.height(16.dp))
                Text("☕ 觉得有用?欢迎扫码请开发者喝杯咖啡", style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(8.dp))
                Image(
                    painter = painterResource(R.drawable.payme),
                    contentDescription = "赞赏二维码",
                    modifier = Modifier
                        .align(Alignment.CenterHorizontally)
                        .size(220.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .combinedClickable(
                            onClick = {},
                            onLongClick = { qrSaver.launch("melonmail-support.jpg") },
                        ),
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "长按二维码可保存到手机",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.align(Alignment.CenterHorizontally),
                )
            }
        }
    }
}

@Composable
private fun VersionRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

// ---------------------------------------------------------------------------
// 公共小部件
// ---------------------------------------------------------------------------

@Composable
private fun LoadMoreEffect(listState: LazyListState, enabled: Boolean, onLoadMore: () -> Unit) {
    val shouldLoad by remember {
        derivedStateOf {
            val info = listState.layoutInfo
            val total = info.totalItemsCount
            val last = info.visibleItemsInfo.lastOrNull()?.index ?: -1
            total > 0 && last >= total - 4
        }
    }
    LaunchedEffect(shouldLoad, enabled) {
        if (shouldLoad && enabled) onLoadMore()
    }
}

@Composable
private fun LoadingFooter() {
    Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) {
        CircularProgressIndicator(Modifier.size(28.dp))
    }
}

@Composable
private fun SearchField(value: String, onChange: (String) -> Unit) {
    Row(
        Modifier
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .fillMaxWidth()
            .clip(RoundedCornerShape(24.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(horizontal = 14.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Default.Search, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(8.dp))
        Box(Modifier.weight(1f)) {
            if (value.isEmpty()) Text("搜索(当前列表)", color = MaterialTheme.colorScheme.onSurfaceVariant)
            BasicTextField(
                value = value,
                onValueChange = onChange,
                singleLine = true,
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onSurface),
                cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun SectionHeader(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(start = 4.dp, top = 4.dp),
    )
}

@Composable
private fun SettingsCard(content: @Composable ColumnScope.() -> Unit) {
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = 1.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp)) { content() }
    }
}

private val AvatarColors = listOf(
    Color(0xFF2D6CDF), Color(0xFF34A853), Color(0xFF7E57C2),
    Color(0xFF00897B), Color(0xFFEF6C00), Color(0xFFD32F2F),
    Color(0xFF5C6BC0), Color(0xFF0097A7),
)

@Composable
private fun Avatar(seed: String, size: Int = 44) {
    val color = AvatarColors[abs(seed.hashCode()) % AvatarColors.size]
    Box(Modifier.size(size.dp).clip(CircleShape).background(color), contentAlignment = Alignment.Center) {
        Text(seed.trim().firstOrNull()?.uppercase() ?: "?", color = Color.White, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun ErrorText(message: String) {
    Text("错误: $message", color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(16.dp))
}

@Composable
private fun ConfigHint(onSettings: () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("请先在设置里填写服务器地址和 API Token")
        Button(onClick = onSettings) { Text("去设置") }
    }
}

private fun reRegister(scope: CoroutineScope, vm: MailViewModel, onResult: (String) -> Unit) {
    FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
        val token = if (task.isSuccessful) task.result else null
        scope.launch {
            if (token.isNullOrBlank()) {
                onResult("获取 FCM token 失败"); return@launch
            }
            vm.settings.setFcmToken(token)
            val resp = runCatching { Api.service?.registerToken(TokenRegister(token)) }.getOrNull()
            onResult(if (resp != null) "已重新上报(服务器设备数: ${resp.count})" else "上报失败,检查服务器地址 / API Token")
        }
    }
}
