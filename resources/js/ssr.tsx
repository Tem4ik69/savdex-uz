import { createInertiaApp } from '@inertiajs/react';
import createServer from '@inertiajs/react/server';
import { renderToString } from 'react-dom/server';
import { resolvePage } from '@/lib/pages';
import { setLocale } from '@/lib/locale';
import { setTranslations } from '@/lib/i18n';
import { setMarketBase } from '@/routes';

const appName = 'SAVDEX';

createServer((page) =>
    createInertiaApp({
        page,
        render: renderToString,
        title: (title) => (title ? `${title} · ${appName}` : appName),
        resolve: resolvePage,
        setup: ({ App, props }) => {
            // Как в app.tsx: язык и словарь — до отрисовки, иначе
            // серверная разметка соберётся с ключами вместо перевода
            // и ссылками без языкового префикса
            const shared = (props.initialPage.props ?? {}) as {
                locale?: string;
                translations?: Record<string, unknown> | null;
                marketLinks?: { base?: string };
            };

            if (typeof shared.locale === 'string') setLocale(shared.locale);
            setMarketBase(shared.marketLinks?.base);
            if (shared.translations) setTranslations(shared.translations, shared.locale ?? 'ru');

            return <App {...props} />;
        },
    }),
);
