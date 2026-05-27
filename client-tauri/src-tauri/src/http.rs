//! Shared reqwest client with cookie store and the worker `X-YQGL-Client-Token` header
//! injected on every request. Keep this file backend-free so all command modules just
//! call `http::client(state).get(url)…`.

use std::sync::Arc;

use once_cell::sync::Lazy;
use parking_lot::RwLock;
use reqwest::{header::{HeaderMap, HeaderName, HeaderValue}, Client, ClientBuilder};

use crate::config::ConfigState;

static CLIENT_CELL: Lazy<RwLock<Option<Arc<Client>>>> = Lazy::new(|| RwLock::new(None));

fn build(cookie_token: &str, client_token: &str) -> Client {
    let mut headers = HeaderMap::new();
    if !client_token.is_empty() {
        if let Ok(v) = HeaderValue::from_str(client_token) {
            headers.insert(HeaderName::from_static("x-yqgl-client-token"), v);
        }
    }
    if !cookie_token.is_empty() {
        // Add cookie via cookie store (set on first request) — simpler: rely on cookies feature
        // and an initial /api/auth/me + cookie_token preset is handled per-call.
    }

    ClientBuilder::new()
        .cookie_store(true)
        .default_headers(headers)
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .expect("reqwest client build")
}

pub fn refresh(state: &ConfigState) {
    let cfg = state.read();
    let client = build(&cfg.cookie_token, &cfg.client_token);
    *CLIENT_CELL.write() = Some(Arc::new(client));
}

pub fn client(state: &ConfigState) -> Arc<Client> {
    if let Some(c) = CLIENT_CELL.read().clone() {
        return c;
    }
    refresh(state);
    CLIENT_CELL.read().clone().unwrap()
}

pub fn base_url(state: &ConfigState) -> String {
    state.read().base_url()
}

pub fn url(state: &ConfigState, path: &str) -> String {
    let base = base_url(state);
    if path.starts_with('/') {
        format!("{base}{path}")
    } else {
        format!("{base}/{path}")
    }
}
