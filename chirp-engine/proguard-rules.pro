# PocketCHIRP CHIRP Engine R8 rules
#
# Android manifest entry points and AIDL-generated Binder code are directly
# referenced and are handled by R8. Chaquopy supplies its own runtime rules.
# Keep these exported Android entry-point class names explicitly because they
# are instantiated by Android rather than by application Java code.
-keepnames class com.wg5eek.pocketchirp.engine.EngineInfoActivity
-keepnames class com.wg5eek.pocketchirp.engine.PocketChirpEngineService
