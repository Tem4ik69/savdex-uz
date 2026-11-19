import { useSyncExternalStore } from 'react';

/**
 * Данные демо в браузере: заказы и кабинет продавца.
 *
 * То же, что корзина (store.ts), но для произвольного значения: пока
 * сервера маркетплейса нет, оформленный заказ и заявка продавца живут в
 * localStorage, чтобы путь можно было пройти целиком. На сервере (SSR)
 * и до гидрации отдаётся начальное значение.
 */
export interface Local<T> {
    subscribe: (listener: () => void) => () => void;
    get: () => T;
    initial: () => T;
    set: (next: T) => void;
}

export function createLocal<T>(key: string, initial: T): Local<T> {
    let state = initial;
    let loaded = false;
    const listeners = new Set<() => void>();

    function load(): void {
        if (loaded || typeof window === 'undefined') return;
        loaded = true;

        try {
            const raw = window.localStorage.getItem(key);

            if (raw) state = JSON.parse(raw) as T;
        } catch {
            // Закрытое хранилище — данные живут до перезагрузки
        }
    }

    return {
        subscribe(listener) {
            load();
            listeners.add(listener);
            listener();

            return () => listeners.delete(listener);
        },
        get: () => state,
        initial: () => initial,
        set(next) {
            load();
            state = next;

            try {
                window.localStorage.setItem(key, JSON.stringify(next));
            } catch {
                // см. load()
            }

            listeners.forEach((notify) => notify());
        },
    };
}

export function useLocal<T>(store: Local<T>): T {
    return useSyncExternalStore(store.subscribe, store.get, store.initial);
}
