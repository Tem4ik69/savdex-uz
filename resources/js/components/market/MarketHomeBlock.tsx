import { ArrowRight, Store } from 'lucide-react';
import { useEffect } from 'react';
import { MarketPhoto } from '@/components/market/MarketPhoto';
import { Link } from '@/components/ui/Link';
import { t } from '@/lib/i18n';
import { useApi } from '@/market/api';
import { sum } from '@/market/format';
import { loadCategories, useCategories } from '@/market/store';
import type { MarketListing } from '@/market/types';
import { routes } from '@/routes';

/** Сколько товаров в ряду блока — остальное в самом маркетплейсе */
const SHOWN = 10;

/**
 * Блок маркетплейса на главной savdex.uz (ТЗ 18.11, раздел 3: «на
 * savdex.uz — на видном месте»): что это, кнопки «в маркетплейс» и «стать
 * продавцом», разделы каталога и ряд популярных товаров.
 *
 * Данные — те же /market/api/… (они отвечают и на основном адресе), уже в
 * браузере: главная не ждёт маркетплейса, а если он не ответил — блок
 * остаётся без ряда товаров, а не пропадает. Ссылки ведут на /market/…,
 * откуда сервер переводит на адрес маркетплейса, если он свой.
 *
 * Показывается, только когда маркетплейс открыт (общий проп market) —
 * на боевом его пока нет, как и пункта в шапке.
 */
export function MarketHomeBlock() {
    const categories = useCategories();
    const popular = useApi<MarketListing>('catalog?sort=popular');
    const items = popular.data?.items.slice(0, SHOWN) ?? [];
    const currency = t('catalog.currency_uzs');

    useEffect(loadCategories, []);

    return (
        <section className="section--tight">
            <div className="container">
                <div className="mk-home">
                    <div className="mk-home__intro">
                        <span className="mk-home__eyebrow">
                            <Store size={14} aria-hidden /> SavdEx Market
                        </span>
                        <h2>{t('home.market_title')}</h2>
                        <p>{t('home.market_lead')}</p>
                        <div className="mk-home__cta">
                            <Link href={routes.market} className="mk-home__go">
                                {t('home.market_open')} <ArrowRight size={16} aria-hidden />
                            </Link>
                            <Link href={routes.marketSell} className="mk-home__sell">
                                {t('home.market_sell')}
                            </Link>
                        </div>
                        {categories && categories.length > 0 && (
                            <nav className="mk-home__cats" aria-label={t('home.market_categories')}>
                                {categories.slice(0, 8).map((c) => (
                                    <Link key={c.slug} href={`${routes.marketCatalog}?category=${c.slug}`}>
                                        <span aria-hidden>{c.emoji}</span> {c.name}
                                    </Link>
                                ))}
                            </nav>
                        )}
                    </div>

                    {(popular.loading || items.length > 0) && (
                        <div className="mk-home__goods">
                            <div className="mk-home__bar">
                                <h3>{t('home.market_popular')}</h3>
                                <Link href={`${routes.marketCatalog}?sort=popular`}>
                                    {t('home.market_all')} <ArrowRight size={14} aria-hidden />
                                </Link>
                            </div>
                            <ul className="mk-home__row" aria-busy={popular.loading}>
                                {popular.loading
                                    ? Array.from({ length: 5 }, (_, i) => (
                                          <li key={i} className="mk-home__item mk-home__item--ghost" aria-hidden>
                                              <span className="mk-home__ph" />
                                              <span className="mk-home__line" />
                                              <span className="mk-home__line mk-home__line--short" />
                                          </li>
                                      ))
                                    : items.map((p) => (
                                          <li key={p.id} className="mk-home__item">
                                              <Link href={routes.marketProduct(p.slug)}>
                                                  <span className="mk-home__ph">
                                                      <MarketPhoto image={p.image} id={p.id} category={p.category} />
                                                  </span>
                                                  <b>
                                                      {sum(p.price)} <i>{currency}</i>
                                                  </b>
                                                  {p.oldPrice && p.oldPrice > p.price && <s>{sum(p.oldPrice)}</s>}
                                                  <span className="mk-home__name">{p.title}</span>
                                              </Link>
                                          </li>
                                      ))}
                            </ul>
                        </div>
                    )}
                </div>
            </div>
        </section>
    );
}
