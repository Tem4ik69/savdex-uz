import { useSyncExternalStore } from 'react';

/**
 * Корзина и избранное маркетплейса — пока в браузере.
 *
 * Серверной корзины ещё нет (ТЗ 18.11): количество по товарам лежит в
 * localStorage, чтобы демо можно было пройти от карточки до корзины.
 * С сервером этот файл заменится запросами, вызовы останутся теми же.
 *
 * На сервере (SSR) и до гидрации корзина пустая — иначе разметка
 * сервера и браузера разошлась бы.
 */

type Quantities = Record<number, number>;

const EMPTY: Quantities = {};

function createStore(key: string) {
    let state: Quantities = EMPTY;
    let loaded = false;
    const listeners = new Set<() => void>();

    function load(): void {
        if (loaded || typeof window === 'undefined') return;
        loaded = true;

        try {
            const raw = window.localStorage.getItem(key);
            const parsed: unknown = raw ? JSON.parse(raw) : null;

            if (parsed && typeof parsed === 'object') state = parsed as Quantities;
        } catch {
            // Закрытое хранилище (приватное окно) — корзина живёт до перезагрузки
        }
    }

    function write(next: Quantities): void {
        state = next;

        try {
            window.localStorage.setItem(key, JSON.stringify(next));
        } catch {
            // см. load()
        }

        listeners.forEach((notify) => notify());
    }

    return {
        subscribe(listener: () => void): () => void {
            load();
            listeners.add(listener);
            // Первое чтение после гидрации: хранилище могло быть непустым
            listener();

            return () => listeners.delete(listener);
        },
        get: (): Quantities => state,
        set(id: number, quantity: number): void {
            load();

            const next = { ...state };

            if (quantity > 0) next[id] = quantity;
            else delete next[id];

            write(next);
        },
        clear: (): void => write(EMPTY),
    };
}

const cart = createStore('savdex.market.cart');
const favorites = createStore('savdex.market.favorites');

const serverSnapshot = (): Quantities => EMPTY;

export function useCart(): Quantities {
    return useSyncExternalStore(cart.subscribe, cart.get, serverSnapshot);
}

export function useFavorites(): Quantities {
    return useSyncExternalStore(favorites.subscribe, favorites.get, serverSnapshot);
}

export function setCartQuantity(id: number, quantity: number): void {
    cart.set(id, quantity);
}

export function addToCart(id: number, quantity = 1): void {
    cart.set(id, (cart.get()[id] ?? 0) + quantity);
}

export function toggleFavorite(id: number): void {
    favorites.set(id, favorites.get()[id] ? 0 : 1);
}

export function clearCart(): void {
    cart.clear();
}

/** Сколько штук в корзине всего — для значка в шапке. */
export function cartCount(items: Quantities): number {
    return Object.values(items).reduce((sum, quantity) => sum + quantity, 0);
}
