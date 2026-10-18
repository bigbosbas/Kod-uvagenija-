const { S3Client, GetObjectCommand } = require("@aws-sdk/client-s3");
const { getSignedUrl } = require("@aws-sdk/s3-request-presigner");

// Timeweb S3 — стандартный S3 API, поэтому официальный AWS SDK работает как есть,
// просто с другим endpoint. Бакет ПРИВАТНЫЙ — файл недоступен напрямую, только
// через подписанную временную ссылку, которую генерируем здесь после проверки
// оплаты (см. routes/verify-access.js).
const PRESIGNED_URL_TTL_SECONDS = 15 * 60; // 15 минут

function getS3Client() {
  const endpoint = process.env.S3_ENDPOINT;
  const region = process.env.S3_REGION || "ru-1";
  const accessKeyId = process.env.S3_ACCESS_KEY_ID;
  const secretAccessKey = process.env.S3_SECRET_ACCESS_KEY;

  if (!endpoint || !accessKeyId || !secretAccessKey) {
    throw new Error("S3_ENDPOINT / S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY не заданы");
  }

  return new S3Client({
    endpoint,
    region,
    credentials: { accessKeyId, secretAccessKey },
    forcePathStyle: true,
  });
}

// PDF книг лежат в том же приватном бакете, что и PDF «Кода уважения».
// Ключи по умолчанию — под них и загружаются файлы; переменные окружения
// позволяют переложить файл, не трогая код.
const BOOK_FILES = {
  book_vliyanie: {
    key: () => process.env.S3_BOOK_VLIYANIE_KEY || "books/nevidimaya-energiya-vliyaniya.pdf",
    filename: "Nevidimaya-energiya-vliyaniya.pdf",
  },
  book_obshchenie: {
    key: () => process.env.S3_BOOK_OBSHCHENIE_KEY || "books/skrytaya-vlast-obshcheniya.pdf",
    filename: "Skrytaya-vlast-obshcheniya.pdf",
  },
};

async function signDownload(key, filename) {
  const bucket = process.env.S3_BUCKET;
  if (!bucket || !key) {
    throw new Error("S3_BUCKET / ключ файла не заданы");
  }

  const client = getS3Client();
  const command = new GetObjectCommand({
    Bucket: bucket,
    Key: key,
    ResponseContentDisposition: `attachment; filename="${filename}"`,
  });

  return getSignedUrl(client, command, { expiresIn: PRESIGNED_URL_TTL_SECONDS });
}

async function getPdfDownloadUrl() {
  return signDownload(process.env.S3_PDF_KEY, "Kod-uvazheniya.pdf");
}

async function getBookDownloadUrl(product) {
  const file = BOOK_FILES[product];
  if (!file) throw new Error(`Неизвестная книга: ${product}`);
  return signDownload(file.key(), file.filename);
}

module.exports = { getPdfDownloadUrl, getBookDownloadUrl, PRESIGNED_URL_TTL_SECONDS };
