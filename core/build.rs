fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Ensure protoc is available via vendored binary for reproducible builds
    if let Ok(path) = protoc_bin_vendored::protoc_bin_path() {
        std::env::set_var("PROTOC", path);
    }
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .compile(
            &[
                "proto/event.proto",
                "proto/agent.proto",
                "proto/plugin.proto",
                "proto/action.proto",
            ],
            &["proto"],
        )?;
    Ok(())
}
