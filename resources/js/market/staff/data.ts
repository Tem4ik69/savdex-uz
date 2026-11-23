import { useCallback, useState } from 'react';
import { api, ApiError, useApi } from '@/market/api';
import { notify } from '@/market/store';

/**
 * Данные экранов склада и пункта выдачи: настоящий адрес, а пока сервер
 * отвечает на него 404 (адреса ещё нет — контракт в staff/contract.ts) —
 * образец того же вида с пометкой sample. Кнопки в образце меняют только
 * копию в браузере: так экран можно пройти целиком до сервера.
 */
export interface StaffData<T> {
    data: T | null;
    /** Показан образец: адреса на сервере ещё нет */
    sample: boolean;
    loading: boolean;
    error: string | null;
    /** 403 — не сотрудник этого склада или пункта; 401 — нужен вход */
    status: number | null;
    reload: () => void;
    /** Поправить образец в браузере (на настоящих данных — перечитать с сервера) */
    patch: (change: (current: T) => T) => void;
}

export function useStaffData<T>(path: string | null, sample: () => T): StaffData<T> {
    const loaded = useApi<T>(path);
    const [local, setLocal] = useState<{ path: string | null; data: T } | null>(null);
    const isSample = loaded.status === 404;
    const data = isSample ? (local?.path === path ? local.data : sample()) : loaded.data;
    const reload = loaded.reload;

    const patch = useCallback(
        (change: (current: T) => T) => {
            if (!isSample) {
                reload();

                return;
            }

            setLocal((prev) => ({ path, data: change(prev?.path === path ? prev.data : sample()) }));
        },
        // sample — функция образца, своя у каждого экрана и не меняется
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [isSample, path, reload],
    );

    return {
        data,
        sample: isSample,
        loading: loaded.loading,
        error: isSample ? null : loaded.error,
        status: isSample ? null : loaded.status,
        reload,
        patch,
    };
}

/**
 * Действие сотрудника: POST на сервер; в образце — ничего не отправляем,
 * только сообщение (экран сам правит образец через patch). Возвращает ответ
 * сервера, 'sample' — в образце, null — отказ (сообщение уже показано,
 * ошибки полей — в errors).
 */
export async function staffAction<R = { message?: string }>(
    path: string,
    body: Record<string, unknown>,
    sample: boolean,
    sampleMessage: string,
    errors?: (fields: Record<string, string[]>) => void,
): Promise<R | 'sample' | null> {
    if (sample) {
        notify(sampleMessage);

        return 'sample';
    }

    try {
        const result = await api<R & { message?: string }>(path, { body });

        if (result.message) notify(result.message);

        return result;
    } catch (failure) {
        if (failure instanceof ApiError) {
            errors?.(failure.errors);
            notify(failure.message, true);
        }

        return null;
    }
}
