# Native code reads these classes' fields and calls their methods by name: keep them whole.
-keep class com.k2fsa.sherpa.onnx.** { *; }
-keep class ai.onnxruntime.** { *; }
