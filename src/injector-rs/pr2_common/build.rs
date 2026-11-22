// 构建期信息：让 exe 自己知道它是哪个版本编出来的。
//
// 值由 src/build_injector.ps1（或调用它的 build.ps1 / release.ps1）通过环境
// 变量传进来，cargo 再交给 build script。没有这些变量时写成空串，
// 启动器显示成 dev —— 开发构建不该谎报一个发行版本号。
//
// 这里不跑 git：构建脚本已经算好了 commit 与是否有未提交改动，build script
// 只做转交，CI 上没有 git 也不影响编译。

fn main() {
    println!("cargo:rerun-if-env-changed=PR2_VERSION");
    println!("cargo:rerun-if-env-changed=PR2_COMMIT");
    println!("cargo:rerun-if-env-changed=PR2_DIRTY");
    println!("cargo:rerun-if-changed=build.rs");

    for (env, key) in [
        ("PR2_VERSION", "PR2_BUILD_VERSION"),
        ("PR2_COMMIT", "PR2_BUILD_COMMIT"),
        ("PR2_DIRTY", "PR2_BUILD_DIRTY"),
    ] {
        let value = std::env::var(env).unwrap_or_default();
        // 只保留干净的字符：这个值会进 cargo:rustc-env，换行会破坏协议。
        let clean: String = value
            .chars()
            .filter(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '_' | '+'))
            .take(32)
            .collect();
        println!("cargo:rustc-env={key}={clean}");
    }
}
