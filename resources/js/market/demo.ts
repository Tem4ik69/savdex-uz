/**
 * Демо-данные маркетплейса.
 *
 * Бэкенда каталога ещё нет (ТЗ 18.11): товары, категории и продавцы
 * лежат здесь в том виде, в каком страницы будут получать их пропсами.
 * Появится сервер — этот файл уходит, типы остаются.
 *
 * Фотографий пока нет: вместо них значок на цветной подложке.
 */

export interface MarketSeller {
    slug: string;
    name: string;
    /** Продавец прошёл проверку (OneID или документы) */
    verified: boolean;
    rating: number;
}

export interface MarketVariant {
    /** «Цвет», «Размер», «Объём» */
    name: string;
    options: string[];
}

export interface MarketProduct {
    id: number;
    slug: string;
    title: string;
    /** Значок вместо фотографии и цвет подложки под ним */
    emoji: string;
    tint: string;
    /** Цена в сумах; oldPrice — зачёркнутая, null — скидки нет */
    price: number;
    oldPrice: number | null;
    rating: number;
    reviews: number;
    sold: number;
    /** Остаток на складе; 0 — купить нельзя */
    stock: number;
    category: string;
    seller: string;
    badge: 'hit' | 'new' | 'sale' | null;
    variants: MarketVariant[];
    specs: [string, string][];
    description: string;
}

export interface MarketCategory {
    slug: string;
    name: string;
    emoji: string;
    /** Подразделы; в каждом — группы товаров (третий уровень) */
    children: { name: string; items: string[] }[];
}

/** Дерево категорий — три уровня: раздел, подраздел, группа товаров. */
export const CATEGORIES: MarketCategory[] = [
    {
        slug: 'electronics',
        name: 'Электроника',
        emoji: '📱',
        children: [
            { name: 'Смартфоны', items: ['Android', 'Кнопочные телефоны', 'Чехлы и стёкла', 'Зарядные устройства'] },
            { name: 'Наушники', items: ['Беспроводные', 'Накладные', 'Игровые', 'Для спорта'] },
            { name: 'Умные часы', items: ['Смарт-часы', 'Фитнес-браслеты', 'Ремешки', 'Детские часы'] },
            { name: 'Ноутбуки', items: ['Для учёбы и офиса', 'Игровые', 'Планшеты', 'Сумки и подставки'] },
            { name: 'Аксессуары', items: ['Пауэрбанки', 'Кабели и переходники', 'Колонки', 'Карты памяти'] },
        ],
    },
    {
        slug: 'appliances',
        name: 'Бытовая техника',
        emoji: '🔌',
        children: [
            { name: 'Для кухни', items: ['Чайники', 'Кофеварки', 'Блендеры и миксеры', 'Микроволновые печи', 'Мультиварки'] },
            { name: 'Для дома', items: ['Пылесосы', 'Утюги и отпариватели', 'Стиральные машины', 'Швейные машины'] },
            { name: 'Климат', items: ['Обогреватели', 'Кондиционеры', 'Вентиляторы', 'Увлажнители'] },
            { name: 'Красота и уход', items: ['Фены', 'Триммеры и бритвы', 'Выпрямители', 'Весы'] },
        ],
    },
    {
        slug: 'clothes',
        name: 'Одежда',
        emoji: '👕',
        children: [
            { name: 'Женская', items: ['Платья', 'Блузки и рубашки', 'Брюки и джинсы', 'Национальная одежда'] },
            { name: 'Мужская', items: ['Рубашки', 'Футболки и поло', 'Брюки и джинсы', 'Костюмы'] },
            { name: 'Детская', items: ['Для девочек', 'Для мальчиков', 'Для малышей', 'Школьная форма'] },
            { name: 'Верхняя одежда', items: ['Куртки', 'Пуховики', 'Пальто', 'Чапаны'] },
        ],
    },
    {
        slug: 'shoes',
        name: 'Обувь',
        emoji: '👟',
        children: [
            { name: 'Женская', items: ['Туфли', 'Кроссовки', 'Ботинки и сапоги', 'Сандалии', 'Домашняя'] },
            { name: 'Мужская', items: ['Кроссовки', 'Туфли', 'Ботинки', 'Сандалии и шлёпанцы'] },
            { name: 'Детская', items: ['Для девочек', 'Для мальчиков', 'Школьная', 'Зимняя'] },
            { name: 'Спортивная', items: ['Для бега', 'Для зала', 'Футбольная', 'Треккинговая'] },
        ],
    },
    {
        slug: 'home',
        name: 'Дом и интерьер',
        emoji: '🛋️',
        children: [
            { name: 'Текстиль', items: ['Постельное бельё', 'Одеяла и подушки', 'Курпачи', 'Полотенца', 'Шторы'] },
            { name: 'Посуда', items: ['Казаны', 'Сковороды и кастрюли', 'Ляганы и пиалы', 'Чайные сервизы'] },
            { name: 'Мебель', items: ['Столы и стулья', 'Шкафы и полки', 'Диваны и кресла', 'Матрасы'] },
            { name: 'Освещение', items: ['Люстры', 'Настольные лампы', 'Лампочки', 'Гирлянды'] },
            { name: 'Хранение', items: ['Контейнеры', 'Вешалки', 'Корзины', 'Органайзеры'] },
        ],
    },
    {
        slug: 'beauty',
        name: 'Красота',
        emoji: '💄',
        children: [
            { name: 'Уход за лицом', items: ['Кремы', 'Очищение', 'Маски', 'Солнцезащита'] },
            { name: 'Волосы', items: ['Шампуни', 'Бальзамы и маски', 'Окрашивание', 'Укладка'] },
            { name: 'Макияж', items: ['Для лица', 'Для глаз', 'Для губ', 'Кисти и спонжи'] },
            { name: 'Парфюмерия', items: ['Женская', 'Мужская', 'Наборы', 'Аттары'] },
        ],
    },
    {
        slug: 'kids',
        name: 'Детям',
        emoji: '🧸',
        children: [
            { name: 'Игрушки', items: ['Конструкторы', 'Куклы', 'Машинки', 'Мягкие игрушки', 'Настольные игры'] },
            { name: 'Для малышей', items: ['Подгузники', 'Коляски', 'Кроватки', 'Бутылочки и соски'] },
            { name: 'Школа', items: ['Рюкзаки', 'Тетради и дневники', 'Пеналы', 'Творчество'] },
            { name: 'Детское питание', items: ['Смеси', 'Каши', 'Пюре', 'Соки и вода'] },
        ],
    },
    {
        slug: 'food',
        name: 'Продукты',
        emoji: '🥗',
        children: [
            { name: 'Чай и кофе', items: ['Чёрный чай', 'Зелёный чай', 'Кофе в зёрнах', 'Растворимый кофе'] },
            { name: 'Сладости', items: ['Халва и парварда', 'Навват', 'Шоколад', 'Печенье'] },
            { name: 'Сухофрукты и орехи', items: ['Курага и изюм', 'Миндаль', 'Грецкий орех', 'Фисташки'] },
            { name: 'Бакалея', items: ['Рис для плова', 'Масло', 'Мука', 'Специи'] },
        ],
    },
    {
        slug: 'tools',
        name: 'Ремонт и стройка',
        emoji: '🛠️',
        children: [
            { name: 'Инструменты', items: ['Дрели и шуруповёрты', 'Болгарки', 'Ручной инструмент', 'Измерительный'] },
            { name: 'Сантехника', items: ['Смесители', 'Душевые системы', 'Трубы и фитинги', 'Унитазы и раковины'] },
            { name: 'Электрика', items: ['Розетки и выключатели', 'Кабель', 'Автоматы', 'Удлинители'] },
            { name: 'Отделка', items: ['Краски', 'Обои', 'Ламинат и плитка', 'Клеи и герметики'] },
        ],
    },
    {
        slug: 'auto',
        name: 'Авто',
        emoji: '🚗',
        children: [
            { name: 'Аксессуары', items: ['Чехлы и коврики', 'Держатели', 'Видеорегистраторы', 'Компрессоры'] },
            { name: 'Масла и химия', items: ['Моторные масла', 'Антифриз', 'Автошампуни', 'Полироли'] },
            { name: 'Шины и диски', items: ['Летние шины', 'Зимние шины', 'Диски', 'Колпаки'] },
        ],
    },
    {
        slug: 'sport',
        name: 'Спорт и отдых',
        emoji: '⚽',
        children: [
            { name: 'Фитнес', items: ['Гантели и гири', 'Коврики', 'Эспандеры', 'Тренажёры'] },
            { name: 'Туризм', items: ['Палатки', 'Спальные мешки', 'Термосы', 'Мангалы'] },
            { name: 'Велосипеды', items: ['Взрослые', 'Детские', 'Самокаты', 'Запчасти и шлемы'] },
            { name: 'Сумки и рюкзаки', items: ['Городские рюкзаки', 'Спортивные сумки', 'Чемоданы', 'Поясные сумки'] },
        ],
    },
    {
        slug: 'office',
        name: 'Канцтовары',
        emoji: '📚',
        children: [
            { name: 'Бумага', items: ['Для принтера', 'Тетради', 'Блокноты', 'Стикеры'] },
            { name: 'Письменные', items: ['Ручки', 'Карандаши', 'Маркеры', 'Корректоры'] },
            { name: 'Для офиса', items: ['Папки и файлы', 'Степлеры', 'Калькуляторы', 'Доски'] },
            { name: 'Книги', items: ['Художественные', 'Учебники', 'Детские', 'На узбекском'] },
        ],
    },
];

export const SELLERS: MarketSeller[] = [
    { slug: 'chorsu-tech', name: 'Chorsu Tech', verified: true, rating: 4.8 },
    { slug: 'technomir', name: 'TechnoMir', verified: true, rating: 4.7 },
    { slug: 'oltin-vodiy', name: 'Oltin Vodiy', verified: true, rating: 4.6 },
    { slug: 'namangan-metall', name: 'Namangan Metall', verified: true, rating: 4.9 },
    { slug: 'samarqand-tekstil', name: 'Samarqand Tekstil', verified: true, rating: 4.8 },
    { slug: 'bolajon', name: 'Bolajon', verified: false, rating: 4.7 },
    { slug: 'guli-cosmetics', name: 'Guli Cosmetics', verified: true, rating: 4.6 },
    { slug: 'usta-market', name: 'Usta Market', verified: true, rating: 4.7 },
];

const WARRANTY: [string, string] = ['Гарантия', '12 месяцев'];

export const PRODUCTS: MarketProduct[] = [
    {
        id: 1, slug: 'smartfon-nova-x5-256', title: 'Смартфон Nova X5, 8/256 ГБ', emoji: '📱', tint: '#e0ecff',
        price: 3_490_000, oldPrice: 4_290_000, rating: 4.8, reviews: 312, sold: 1200, stock: 14,
        category: 'electronics', seller: 'chorsu-tech', badge: 'hit',
        variants: [{ name: 'Цвет', options: ['Синий', 'Чёрный', 'Зелёный'] }, { name: 'Память', options: ['128 ГБ', '256 ГБ'] }],
        specs: [['Экран', '6,7″ AMOLED, 120 Гц'], ['Камера', '50 Мп'], ['Батарея', '5000 мА·ч'], ['SIM', 'Две SIM'], WARRANTY],
        description: 'Яркий экран, быстрая зарядка и камера с ночным режимом. Официальная гарантия продавца.',
    },
    {
        id: 2, slug: 'naushniki-orbit-buds-2', title: 'Беспроводные наушники Orbit Buds 2', emoji: '🎧', tint: '#ede9fe',
        price: 289_000, oldPrice: 420_000, rating: 4.7, reviews: 1840, sold: 5400, stock: 60,
        category: 'electronics', seller: 'technomir', badge: 'hit',
        variants: [{ name: 'Цвет', options: ['Чёрный', 'Белый'] }],
        specs: [['Тип', 'Вкладыши с шумоподавлением'], ['Работа', 'до 28 часов с кейсом'], ['Связь', 'Bluetooth 5.3'], WARRANTY],
        description: 'Активное шумоподавление и быстрая зарядка: 10 минут в кейсе дают два часа музыки.',
    },
    {
        id: 3, slug: 'krossovki-begovye-setka', title: 'Кроссовки мужские беговые, сетка', emoji: '👟', tint: '#dcfce7',
        price: 349_000, oldPrice: 499_000, rating: 4.6, reviews: 96, sold: 310, stock: 22,
        category: 'shoes', seller: 'oltin-vodiy', badge: 'new',
        variants: [{ name: 'Размер', options: ['40', '41', '42', '43', '44'] }],
        specs: [['Верх', 'Дышащая сетка'], ['Подошва', 'Вспененная, 3 см'], ['Сезон', 'Весна — осень']],
        description: 'Лёгкая пара для бега и города. Маломерят на полразмера — берите с запасом.',
    },
    {
        id: 4, slug: 'kazan-chugunnyj-12l', title: 'Казан чугунный 12 л с крышкой', emoji: '🍲', tint: '#ffedd5',
        price: 415_000, oldPrice: null, rating: 4.9, reviews: 540, sold: 2100, stock: 35,
        category: 'home', seller: 'namangan-metall', badge: 'hit',
        variants: [{ name: 'Объём', options: ['8 л', '12 л', '16 л'] }],
        specs: [['Материал', 'Чугун, наманганское литьё'], ['Крышка', 'Алюминиевая'], ['Вес', '9,4 кг'], ['Плита', 'Газ, очаг']],
        description: 'Классический казан для плова на 10–12 порций. Перед первым приготовлением прокалите с маслом.',
    },
    {
        id: 5, slug: 'kofevarka-kapelnaya-12', title: 'Кофеварка капельная 1,2 л', emoji: '☕', tint: '#fef3c7',
        price: 890_000, oldPrice: 1_150_000, rating: 4.5, reviews: 71, sold: 180, stock: 9,
        category: 'appliances', seller: 'technomir', badge: 'sale',
        variants: [],
        specs: [['Объём', '1,2 л — до 10 чашек'], ['Мощность', '900 Вт'], ['Подогрев', 'до 40 минут'], WARRANTY],
        description: 'Варит до десяти чашек за раз и держит кофе горячим. Съёмный фильтр моется под краном.',
    },
    {
        id: 6, slug: 'ryukzak-gorodskoj-25l', title: 'Рюкзак городской 25 л, влагозащита', emoji: '🎒', tint: '#e0f2fe',
        price: 199_000, oldPrice: 280_000, rating: 4.7, reviews: 228, sold: 760, stock: 48,
        category: 'sport', seller: 'samarqand-tekstil', badge: 'new',
        variants: [{ name: 'Цвет', options: ['Красный', 'Серый', 'Чёрный'] }],
        specs: [['Объём', '25 л'], ['Отделение', 'Для ноутбука до 15,6″'], ['Ткань', 'Полиэстер с пропиткой']],
        description: 'Отделение для ноутбука, карман на спинке для документов и порт для зарядки.',
    },
    {
        id: 7, slug: 'konstruktor-520-detalej', title: 'Конструктор детский, 520 деталей', emoji: '🧸', tint: '#fce7f3',
        price: 159_000, oldPrice: 230_000, rating: 4.8, reviews: 403, sold: 1900, stock: 70,
        category: 'kids', seller: 'bolajon', badge: 'hit',
        variants: [],
        specs: [['Деталей', '520'], ['Возраст', 'от 6 лет'], ['Материал', 'Пластик без запаха']],
        description: 'Три модели из одного набора. Детали совместимы с популярными конструкторами.',
    },
    {
        id: 8, slug: 'krem-dlya-lica-50ml', title: 'Крем для лица увлажняющий, 50 мл', emoji: '🧴', tint: '#f3e8ff',
        price: 78_000, oldPrice: null, rating: 4.6, reviews: 1250, sold: 8300, stock: 200,
        category: 'beauty', seller: 'guli-cosmetics', badge: 'new',
        variants: [{ name: 'Объём', options: ['50 мл', '100 мл'] }],
        specs: [['Тип кожи', 'Нормальная и сухая'], ['Состав', 'Гиалуроновая кислота, алоэ'], ['Срок', '24 месяца']],
        description: 'Лёгкая текстура, быстро впитывается. Подходит под макияж.',
    },
    {
        id: 9, slug: 'drel-shurupovert-18v', title: 'Дрель-шуруповёрт 18 В, 2 аккумулятора', emoji: '🛠️', tint: '#e2e8f0',
        price: 720_000, oldPrice: 960_000, rating: 4.7, reviews: 158, sold: 420, stock: 17,
        category: 'tools', seller: 'usta-market', badge: 'sale',
        variants: [],
        specs: [['Напряжение', '18 В'], ['Аккумуляторы', '2 × 2,0 А·ч'], ['Патрон', 'до 13 мм'], ['В комплекте', 'Кейс, 12 бит'], WARRANTY],
        description: 'Два аккумулятора в комплекте: один работает, второй заряжается.',
    },
    {
        id: 10, slug: 'postelnoe-bele-hlopok-2sp', title: 'Постельное бельё, хлопок, 2-спальное', emoji: '🛏️', tint: '#ecfccb',
        price: 329_000, oldPrice: 450_000, rating: 4.9, reviews: 677, sold: 3000, stock: 55,
        category: 'home', seller: 'samarqand-tekstil', badge: 'hit',
        variants: [{ name: 'Цвет', options: ['Голубой', 'Бежевый', 'Белый'] }],
        specs: [['Ткань', 'Хлопок 100 %, сатин'], ['Комплект', 'Пододеяльник, простыня, 2 наволочки'], ['Размер', '2-спальный']],
        description: 'Плотный сатин из узбекского хлопка: не скатывается и не линяет после стирки.',
    },
    {
        id: 11, slug: 'umnye-chasy-pulse-3', title: 'Умные часы Pulse 3, AMOLED', emoji: '⌚', tint: '#dbeafe',
        price: 540_000, oldPrice: 790_000, rating: 4.4, reviews: 89, sold: 240, stock: 0,
        category: 'electronics', seller: 'chorsu-tech', badge: 'sale',
        variants: [{ name: 'Цвет', options: ['Чёрный', 'Серебро'] }],
        specs: [['Экран', '1,43″ AMOLED'], ['Работа', 'до 10 дней'], ['Защита', '5 ATM'], WARRANTY],
        description: 'Пульс, сон, 100 видов тренировок и звонки с запястья.',
    },
    {
        id: 12, slug: 'chajnik-elektricheskij-17', title: 'Чайник электрический 1,7 л, стекло', emoji: '🫖', tint: '#cffafe',
        price: 185_000, oldPrice: 240_000, rating: 4.6, reviews: 344, sold: 1100, stock: 40,
        category: 'appliances', seller: 'technomir', badge: 'new',
        variants: [],
        specs: [['Объём', '1,7 л'], ['Мощность', '2200 Вт'], ['Корпус', 'Термостойкое стекло'], WARRANTY],
        description: 'Закипает за три минуты и отключается сам. Подсветка воды при нагреве.',
    },
];

export function sellerOf(product: MarketProduct): MarketSeller {
    return SELLERS.find((s) => s.slug === product.seller) ?? SELLERS[0];
}

export function categoryOf(slug: string): MarketCategory | undefined {
    return CATEGORIES.find((c) => c.slug === slug);
}

/** Скидка в процентах; 0 — старой цены нет. */
export function discount(product: MarketProduct): number {
    return product.oldPrice ? Math.round((1 - product.price / product.oldPrice) * 100) : 0;
}

/** Подборки-кружки на главной: каждая ведёт в каталог со своим отбором. */
export const STORIES: { label: string; emoji: string; query: string }[] = [
    { label: 'Скидки', emoji: '🔥', query: 'only=sale' },
    { label: 'Новинки', emoji: '✨', query: 'only=new' },
    { label: 'Хиты', emoji: '🏆', query: 'only=hit' },
    { label: 'До 100 000', emoji: '💸', query: 'max=100000' },
    { label: 'Сделано в UZ', emoji: '🇺🇿', query: 'category=home' },
    { label: 'К зиме', emoji: '❄️', query: 'category=clothes' },
    { label: 'Для дома', emoji: '🏠', query: 'category=home' },
    { label: 'Детям', emoji: '🧸', query: 'category=kids' },
    { label: 'Гаджеты', emoji: '🎧', query: 'category=electronics' },
    { label: 'Красота', emoji: '💄', query: 'category=beauty' },
    { label: 'Ремонт', emoji: '🛠️', query: 'category=tools' },
    { label: 'Спорт', emoji: '⚽', query: 'category=sport' },
];

export const BANNERS: { eyebrow: string; title: string; text: string; cta: string; query: string; emoji: string }[] = [
    { eyebrow: 'Скидки ноября', title: 'Техника для дома до −40%', text: 'Заберите в любом пункте выдачи BTS в Ташкенте', cta: 'Смотреть скидки', query: 'only=sale', emoji: '🧺' },
    { eyebrow: 'Выдача в пунктах BTS', title: 'Закажите онлайн — заберите рядом с домом', text: 'Оплата картой или наличными при получении', cta: 'Выбрать товары', query: '', emoji: '📦' },
    { eyebrow: 'Сделано в Узбекистане', title: 'Текстиль и посуда от местных продавцов', text: 'Хлопок из Самарканда, чугун из Намангана', cta: 'В каталог', query: 'category=home', emoji: '🍲' },
];

export const COUPONS: { value: string; text: string; cta: string }[] = [
    { value: '−50 000 сум', text: 'при заказе от 500 000 сум', cta: 'Взять' },
    { value: '−10%', text: 'на первый заказ', cta: 'Взять' },
    { value: '0 сум', text: 'выдача в пункте BTS', cta: 'Подробнее' },
];
