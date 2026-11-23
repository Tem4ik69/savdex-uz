import { plural } from '@/market/format';

const ru = {
    title: 'Мои заказы · SavdEx Market',
    crumbs: 'Путь',
    home: 'Главная',
    heading: 'Мои заказы',
    gateTitle: 'Войдите, чтобы увидеть заказы',
    gateText: 'Заказы хранятся в вашем аккаунте.',
    login: 'Войти',
    failed: 'Заказы не загрузились',
    retry: 'Повторить',
    emptyTitle: 'Заказов пока нет',
    emptyText: 'Оформленные заказы появятся здесь — с их статусом и пунктом выдачи.',
    toCatalog: 'Перейти в каталог',
    order: (number: string) => `Заказ ${number}`,
    items: (n: number) => `${n} ${plural(n, ['товар', 'товара', 'товаров'])}`,
    byCard: 'картой',
    onDelivery: 'при получении',
    currency: 'сум',
};

const uz: typeof ru = {
    title: 'Buyurtmalarim · SavdEx Market',
    crumbs: 'Yo‘l',
    home: 'Bosh sahifa',
    heading: 'Buyurtmalarim',
    gateTitle: 'Buyurtmalarni ko‘rish uchun kiring',
    gateText: 'Buyurtmalar akkauntingizda saqlanadi.',
    login: 'Kirish',
    failed: 'Buyurtmalar yuklanmadi',
    retry: 'Qayta urinish',
    emptyTitle: 'Hozircha buyurtmalar yo‘q',
    emptyText: 'Rasmiylashtirilgan buyurtmalar shu yerda chiqadi — holati va topshirish punkti bilan.',
    toCatalog: 'Katalogga o‘tish',
    order: (number) => `Buyurtma ${number}`,
    items: (n) => `${n} ta mahsulot`,
    byCard: 'karta orqali',
    onDelivery: 'qabul qilganda',
    currency: 'so‘m',
};

export const ordersPageText = { ru, uz };
