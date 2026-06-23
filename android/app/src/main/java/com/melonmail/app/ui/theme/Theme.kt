package com.melonmail.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// 参照 UI 设计稿:蓝色主色 + 浅灰背景 + 白色卡片(平面化)。
private val Blue = Color(0xFF2D6CDF)
private val BlueDark = Color(0xFF5B8DEF)
private val Red = Color(0xFFE8534E)

private val LightColors = lightColorScheme(
    primary = Blue,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDCE7FF),
    onPrimaryContainer = Color(0xFF0B306E),
    secondary = Color(0xFF4F6B8A),
    error = Red,
    background = Color(0xFFF2F4F7),
    onBackground = Color(0xFF1A1C1E),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF1A1C1E),
    surfaceVariant = Color(0xFFEDF0F4),
    onSurfaceVariant = Color(0xFF6B7280),
    outline = Color(0xFFD8DEE6),
    outlineVariant = Color(0xFFE6EAF0),
)

private val DarkColors = darkColorScheme(
    primary = BlueDark,
    onPrimary = Color(0xFF06122B),
    primaryContainer = Color(0xFF1B345E),
    onPrimaryContainer = Color(0xFFDCE7FF),
    secondary = Color(0xFF9FB4D6),
    error = Color(0xFFFF8A85),
    background = Color(0xFF0E1013),
    onBackground = Color(0xFFE6E8EB),
    surface = Color(0xFF181B20),
    onSurface = Color(0xFFE6E8EB),
    surfaceVariant = Color(0xFF23272E),
    onSurfaceVariant = Color(0xFF9AA0A6),
    outline = Color(0xFF343A42),
    outlineVariant = Color(0xFF272C33),
)

@Composable
fun MelonTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        content = content,
    )
}
