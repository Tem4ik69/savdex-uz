import { cn } from '@/lib/cn';
import { findCategory, useCategories } from '@/market/store';

/** Подложки под значок, когда фото нет: цвет — по номеру товара, чтобы не скакал. */
const TINTS = ['#e0ecff', '#ede9fe', '#dcfce7', '#ffedd5', '#fef3c7', '#e0f2fe', '#fce7f3', '#f3e8ff', '#e2e8f0', '#ecfccb', '#dbeafe', '#cffafe'];

/**
 * Фото товара. Пока продавец не загрузил фото, на его месте — значок
 * категории на цветной подложке: карточка без картинки выглядела бы
 * сломанной, а серый квадрат — одинаковым у всех товаров.
 */
export function MarketPhoto({
    image,
    id,
    category,
    alt = '',
    className,
}: {
    image: string | null;
    /** Номер товара — выбирает цвет подложки */
    id: number;
    /** Адрес категории — выбирает значок */
    category?: string;
    alt?: string;
    className?: string;
}) {
    const categories = useCategories();

    if (image) {
        return (
            <span className={cn('mk-photo-box', className)}>
                <img src={image} alt={alt} loading="lazy" decoding="async" />
            </span>
        );
    }

    const emoji = (category && findCategory(categories, category)?.emoji) || '📦';

    return (
        <span className={cn('mk-photo-box mk-photo-box--empty', className)} style={{ background: TINTS[id % TINTS.length] }} aria-hidden>
            {emoji}
        </span>
    );
}
