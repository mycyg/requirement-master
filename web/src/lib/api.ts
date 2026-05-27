// Re-export shim. The real implementation lives in `@yqgl/shared/api`
// so that both web and the upcoming Tauri client can share it.
export { api, isDesktopRuntime } from "@yqgl/shared";
