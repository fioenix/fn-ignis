-- Bảng lưu trữ phiên xác thực và tokens của các nền tảng mạng xã hội (TikTok, Threads, Reels)
CREATE TABLE IF NOT EXISTS platform_credentials (
    platform VARCHAR(32) PRIMARY KEY,
    auth_type VARCHAR(32) NOT NULL DEFAULT 'session_cookies', -- 'oauth2', 'session_cookies', 'api_key'
    credentials_data JSONB NOT NULL,                          -- storageState (cookies, localStorage, tokens)
    is_active BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_credentials_active ON platform_credentials (is_active);
