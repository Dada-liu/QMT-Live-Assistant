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
}

export function getState(key) {
    return AppState[key];
}
