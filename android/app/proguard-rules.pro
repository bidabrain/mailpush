# kotlinx.serialization:保留 @Serializable 生成的序列化器
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class com.melonmail.app.data.** {
    *** Companion;
}
-keepclasseswithmembers class com.melonmail.app.data.** {
    kotlinx.serialization.KSerializer serializer(...);
}
