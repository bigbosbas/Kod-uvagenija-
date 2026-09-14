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

async function getPdfDownloadUrl() {
  const bucket = process.env.S3_BUCKET;
  const key = process.env.S3_PDF_KEY;
  if (!bucket || !key) {
    throw new Error("S3_BUCKET / S3_PDF_KEY не заданы");
  }

  const client = getS3Client();
  const command = new GetObjectCommand({
    Bucket: bucket,
    Key: key,
    ResponseContentDisposition: 'attachment; filename="Kod-uvazheniya.pdf"',
  });

  return getSignedUrl(client, command, { expiresIn: PRESIGNED_URL_TTL_SECONDS });
}

module.exports = { getPdfDownloadUrl, PRESIGNED_URL_TTL_SECONDS };
