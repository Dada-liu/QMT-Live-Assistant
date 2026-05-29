const TOKEN_KEY = 'qmt_token';

export const AppState = {
    serverRunning: false,
    token: null,
    serverInfo: null,
    signals: [],
    theme: 'light',
    pollingInterval: null,
};

export function setState(key, value) {
    AppState[key] = value;
    if (key === 'token') {
        if (value) {
            sessionStorage.setItem(TOKEN_KEY, value);
        } else {
            sessionStorage.removeItem(TOKEN_KEY);
        }
    }
}

export function getState(key) {
    if (key === 'token' && !AppState[key]) {
        AppState[key] = sessionStorage.getItem(TOKEN_KEY) || null;
    }
    return AppState[key];
}

export function getStoredToken() {
    return sessionStorage.getItem(TOKEN_KEY) || null;
}
