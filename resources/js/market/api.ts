import { useCallback, useEffect, useRef, useState } from 'react';
import { localize } from '@/lib/locale';
import { lang } from '@/market/lang';
import { commonText } from '@/market/text/common';

/**
 * Запросы к серверу маркетплейса — /market/api/… (docs/marketplace.md).
 *
 * Ответ — JSON. Запись идёт POST с токеном CSRF из куки XSRF-TOKEN, как
 * у остальных запросов сайта. Языковой префикс подставляется сам —
 * названия категорий и тексты сервера приходят на языке страницы.
 */

export class ApiError extends Error {
    constructor(
        message: string,
        readonly status: number,
        /** Ошибки по полям формы: 422 {errors: {поле: [текст]}} */
        readonly errors: Record<string, string[]> = {},
        readonly data: Record<string, unknown> = {},
    ) {
        super(message);
    }
}

/** Общее сообщение об ошибке — на языке страницы в момент ошибки. */
const fallback = (): string => lang(commonText).requestFailed;

function token(): Record<string, string> {
    const value = document.cookie.match(/XSRF-TOKEN=([^;]+)/)?.[1];

    return value ? { 'X-XSRF-TOKEN': decodeURIComponent(value) } : {};
}

interface Options {
    /** Тело POST: объект уходит JSON, FormData — как есть (загрузка фото) */
    body?: Record<string, unknown> | FormData;
    post?: boolean;
    signal?: AbortSignal;
    /**
     * Что делать, когда сервер ответил «нужен вход» (401): по умолчанию —
     * уйти на вход (сервер запомнил страницу и вернёт на неё), false —
     * отдать ошибку вызвавшему.
     */
    loginRedirect?: boolean;
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
    const { body, signal, loginRedirect = true } = options;
    const post = options.post ?? body !== undefined;
    const form = body instanceof FormData;
    let response: Response;

    try {
        response = await fetch(localize(`/market/api/${path}`), {
            method: post ? 'POST' : 'GET',
            credentials: 'same-origin',
            signal,
            headers: {
                Accept: 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                ...(post ? token() : {}),
                ...(post && !form ? { 'Content-Type': 'application/json' } : {}),
            },
            body: post ? (form ? body : JSON.stringify(body ?? {})) : undefined,
        });
    } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') throw error;

        throw new ApiError(fallback(), 0);
    }

    const data = ((await response.json().catch(() => null)) ?? {}) as Record<string, unknown>;

    if (response.ok) return data as T;

    if (response.status === 401 && loginRedirect) {
        window.location.assign(typeof data.login === 'string' ? data.login : localize('/login'));
    }

    throw new ApiError(
        typeof data.message === 'string' && data.message ? data.message : fallback(),
        response.status,
        (data.errors as Record<string, string[]> | undefined) ?? {},
        data,
    );
}

export interface Loaded<T> {
    data: T | null;
    /** Текст ошибки для показа; null — ошибки нет */
    error: string | null;
    /** Код ответа при ошибке: 404 — «нет такого», 401 — нужен вход, 403 — нельзя */
    status: number | null;
    loading: boolean;
    reload: () => void;
}

/**
 * Данные по адресу: пока грузятся — loading, не получилось — error.
 * path = null — запрос не нужен (например, гостю не грузим корзину).
 * На сервере (SSR) и до первого ответа — loading: разметку страницы
 * отдаём с заглушками, данные приходят уже в браузере.
 */
export function useApi<T>(path: string | null): Loaded<T> {
    const [state, setState] = useState<{ path: string | null; data: T | null; error: string | null; status: number | null }>({
        path: null,
        data: null,
        error: null,
        status: null,
    });
    const [turn, setTurn] = useState(0);
    const alive = useRef(true);

    useEffect(() => {
        alive.current = true;

        return () => {
            alive.current = false;
        };
    }, []);

    useEffect(() => {
        if (path === null) return;

        const controller = new AbortController();

        api<T>(path, { signal: controller.signal, loginRedirect: false })
            .then((data) => alive.current && setState({ path, data, error: null, status: null }))
            .catch((error: unknown) => {
                if (controller.signal.aborted || !alive.current) return;

                const failure = error instanceof ApiError ? error : new ApiError(fallback(), 0);

                setState({ path, data: null, error: failure.message, status: failure.status });
            });

        return () => controller.abort();
    }, [path, turn]);

    const reload = useCallback(() => setTurn((n) => n + 1), []);
    // Ответ на прежний адрес не показываем как ответ на новый
    const fresh = state.path === path;

    return {
        data: fresh ? state.data : null,
        error: fresh ? state.error : null,
        status: fresh ? state.status : null,
        loading: path !== null && !fresh,
        reload,
    };
}
