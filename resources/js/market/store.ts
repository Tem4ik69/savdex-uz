import { useSyncExternalStore } from 'react';
import { api, ApiError } from '@/market/api';
import type { CartSummary, MarketCategory, MarketProductPage } from '@/market/types';

/**
 * Общее состояние маркетплейса в браузере: корзина и избранное
 * вошедшего покупателя, дерево категорий и всплывающее сообщение.
 *
 * Корзина и избранное живут на сервере и только у вошедшего: гостю
 * запрос отвечает «нужен вход», и api() уводит на страницу входа —
 * сервер запоминает, откуда пришли, и возвращает к товару (ТЗ, раздел 4).
 * Здесь — копия ответа сервера, чтобы значок в шапке и кнопки карточек
 * обновлялись сразу на всех частях страницы.
 */

interface State {
    cart: CartSummary | null;
    favorites: number[];
    categories: MarketCategory[] | null;
    notice: { text: string; error: boolean; id: number } | null;
}

let state: State = { cart: null, favorites: [], categories: null, notice: null };
const EMPTY: State = state;
const listeners = new Set<() => void>();

function set(patch: Partial<State>): void {
    state = { ...state, ...patch };
    listeners.forEach((notify) => notify());
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener);

    return () => listeners.delete(listener);
}

function useStore<T>(pick: (s: State) => T): T {
    return useSyncExternalStore(
        subscribe,
        () => pick(state),
        () => pick(EMPTY),
    );
}

export const useCart = (): CartSummary | null => useStore((s) => s.cart);
export const useFavorites = (): number[] => useStore((s) => s.favorites);
export const useCategories = (): MarketCategory[] | null => useStore((s) => s.categories);
export const useNotice = (): State['notice'] => useStore((s) => s.notice);

let noticeTimer: number | undefined;

export function notify(text: string, error = false): void {
    window.clearTimeout(noticeTimer);
    set({ notice: { text, error, id: Date.now() } });
    noticeTimer = window.setTimeout(() => set({ notice: null }), 4000);
}

function failed(error: unknown): void {
    // 401 — api() уже уводит на вход, сообщение не нужно
    if (error instanceof ApiError && error.status !== 401) notify(error.message, true);
}

let sessionFor: number | null | undefined;
let categoriesAsked = false;

/**
 * Загрузить то, что нужно всем страницам: категории — всегда, корзину и
 * избранное — вошедшему. Зовёт раскладка; повторный вызов для того же
 * пользователя ничего не делает.
 */
export function startSession(userId: number | null): void {
    if (!categoriesAsked) {
        categoriesAsked = true;
        api<{ categories: MarketCategory[] }>('categories')
            .then((data) => set({ categories: data.categories }))
            .catch(() => {
                // Без категорий страница работает: меню каталога покажет, что список не загрузился
                categoriesAsked = false;
                set({ categories: [] });
            });
    }

    if (sessionFor === userId) return;
    sessionFor = userId;

    if (userId === null) {
        set({ cart: null, favorites: [] });

        return;
    }

    api<CartSummary>('cart', { loginRedirect: false })
        .then((cart) => set({ cart }))
        .catch(() => undefined);
    api<{ ids: number[] }>('favorites', { loginRedirect: false })
        .then((data) => set({ favorites: data.ids }))
        .catch(() => undefined);
}

/** Положить вариант товара в корзину. true — получилось. */
export async function addToCart(variantId: number, quantity = 1): Promise<boolean> {
    try {
        const data = await api<{ message: string; cart: CartSummary }>('cart/add', { body: { variantId, quantity } });

        set({ cart: data.cart });
        notify(data.message);

        return true;
    } catch (error) {
        failed(error);

        return false;
    }
}

/**
 * «В корзину» с карточки в списке. В карточке нет вариантов, поэтому
 * сначала спрашиваем товар: один вариант — кладём его, несколько
 * (цвет, размер) — выбирать нужно на странице товара ('choose').
 */
export async function addProductToCart(slug: string): Promise<'added' | 'choose' | 'failed'> {
    try {
        const { product } = await api<{ product: MarketProductPage }>(`product/${slug}`);
        const available = product.offers.filter((offer) => offer.stock > 0);

        if (product.offers.length !== 1 || available.length !== 1) return 'choose';

        return (await addToCart(available[0].id)) ? 'added' : 'failed';
    } catch (error) {
        failed(error);

        return 'failed';
    }
}

/** Сколько штук варианта в корзине; 0 — убрать. */
export async function setCartQuantity(variantId: number, quantity: number): Promise<boolean> {
    try {
        const data = await api<{ cart: CartSummary }>(`cart/${variantId}`, { body: { quantity } });

        set({ cart: data.cart });

        return true;
    } catch (error) {
        failed(error);

        return false;
    }
}

export async function toggleFavorite(productId: number): Promise<void> {
    try {
        const data = await api<{ favorite: boolean }>(`favorites/${productId}`, { post: true });

        set({
            favorites: data.favorite ? [productId, ...state.favorites.filter((id) => id !== productId)] : state.favorites.filter((id) => id !== productId),
        });
    } catch (error) {
        failed(error);
    }
}

/** Сколько штук в корзине можно купить сейчас — для значка в шапке. */
export const cartCount = (cart: CartSummary | null): number => cart?.count ?? 0;

/** Все строки корзины подряд, без деления на продавцов. */
export const cartLines = (cart: CartSummary | null) => (cart ? cart.parts.flatMap((part) => part.items) : []);

/** Значок и название категории по её адресу — в том числе вложенной. */
export function findCategory(tree: MarketCategory[] | null, slug: string): { node: MarketCategory; emoji: string } | null {
    const walk = (nodes: MarketCategory[], inherited: string): { node: MarketCategory; emoji: string } | null => {
        for (const node of nodes) {
            const emoji = node.emoji || inherited;

            if (node.slug === slug) return { node, emoji };

            const deeper = walk(node.children, emoji);

            if (deeper) return deeper;
        }

        return null;
    };

    return tree ? walk(tree, '') : null;
}
