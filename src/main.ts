import { Logger, ValidationPipe } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { NestFactory } from '@nestjs/core';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { NestExpressApplication } from '@nestjs/platform-express';
import { join } from 'path';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create<NestExpressApplication>(AppModule, {
    logger: ['error', 'warn', 'log'],
  });
  const config = app.get(ConfigService);

  app.useStaticAssets(join(process.cwd(), 'public'));
  app.useStaticAssets(
    join(process.cwd(), 'node_modules', 'livekit-client', 'dist'),
    { prefix: '/vendor/livekit' },
  );
  // 학생 화면의 PDF 렌더러(pdf.js). 태블릿 브라우저는 iframe PDF 를 인라인으로
  // 그리지 못하므로 canvas 렌더링이 필요하다.
  app.useStaticAssets(
    join(process.cwd(), 'node_modules', 'pdfjs-dist', 'legacy', 'build'),
    { prefix: '/vendor/pdfjs' },
  );
  // 한글 PDF(HWP/Word 내보내기)는 CMap 과 비내장 표준 폰트가 없으면 빈 화면이 된다.
  app.useStaticAssets(
    join(process.cwd(), 'node_modules', 'pdfjs-dist', 'cmaps'),
    {
      prefix: '/vendor/pdfjs/cmaps',
    },
  );
  app.useStaticAssets(
    join(process.cwd(), 'node_modules', 'pdfjs-dist', 'standard_fonts'),
    { prefix: '/vendor/pdfjs/standard_fonts' },
  );

  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    }),
  );

  const swaggerConfig = new DocumentBuilder()
    .setTitle('UniVoice Core API')
    .setDescription(
      'NestJS control plane for the UniVoice realtime translation service',
    )
    .setVersion('0.1.0')
    .addBearerAuth(
      { type: 'http', scheme: 'bearer', bearerFormat: 'JWT' },
      'bearer',
    )
    .build();
  const document = SwaggerModule.createDocument(app, swaggerConfig);
  SwaggerModule.setup('docs', app, document, {
    swaggerOptions: { persistAuthorization: true },
  });

  app.enableCors();
  app.enableShutdownHooks();

  const port = config.get<number>('PORT', 3000);
  await app.listen(port);
  Logger.log(`UniVoice Core API running on http://localhost:${port}`);
  Logger.log(`Swagger UI: http://localhost:${port}/docs`);
}

bootstrap();
