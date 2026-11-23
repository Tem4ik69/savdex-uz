import { plural } from '@/market/format';

const ru = {
    notFoundTitle: 'Продавец не найден · SavdEx Market',
    missingTitle: 'Такого продавца нет',
    failedTitle: 'Страница продавца не загрузилась',
    missingText: 'Возможно, магазин закрылся или ссылка устарела.',
    toCatalog: 'Перейти в каталог',
    retry: 'Повторить',
    crumbs: 'Путь',
    home: 'Главная',
    sellers: 'Продавцы',
    verified: 'Проверенный продавец · компания на SavdEx',
    seller: 'Продавец на SavdEx',
    rating: 'Рейтинг',
    goods: 'Товаров',
    since: 'На SavdEx с',
    items: (total: string, n: number) => `${total} ${plural(n, ['товар', 'товара', 'товаров'])} продавца`,
    companyCard: 'Карточка компании на SavdEx →',
    emptyTitle: 'Продавец пока ничего не выставил',
    emptyText: 'Товары появятся здесь, как только склад примет первую поставку.',
};

const uz: typeof ru = {
    notFoundTitle: 'Sotuvchi topilmadi · SavdEx Market',
    missingTitle: 'Bunday sotuvchi yo‘q',
    failedTitle: 'Sotuvchi sahifasi yuklanmadi',
    missingText: 'Ehtimol, do‘kon yopilgan yoki havola eskirgan.',
    toCatalog: 'Katalogga o‘tish',
    retry: 'Qayta urinish',
    crumbs: 'Yo‘l',
    home: 'Bosh sahifa',
    sellers: 'Sotuvchilar',
    verified: 'Tasdiqlangan sotuvchi · SavdEx’dagi kompaniya',
    seller: 'SavdEx’dagi sotuvchi',
    rating: 'Reyting',
    goods: 'Mahsulotlar',
    since: 'SavdEx’da qachondan',
    items: (total) => `Sotuvchining ${total} ta mahsuloti`,
    companyCard: 'SavdEx’dagi kompaniya kartochkasi →',
    emptyTitle: 'Sotuvchi hali hech narsa qo‘ymagan',
    emptyText: 'Ombor birinchi yetkazmani qabul qilishi bilan mahsulotlar shu yerda chiqadi.',
};

export const shopText = { ru, uz };
