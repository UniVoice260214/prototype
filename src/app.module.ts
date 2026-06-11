import { ClassSerializerInterceptor, Module } from '@nestjs/common';
import { APP_FILTER, APP_GUARD, APP_INTERCEPTOR } from '@nestjs/core';
import { ConfigModule } from '@nestjs/config';
import { TypeOrmModule } from '@nestjs/typeorm';
import { typeOrmAsyncConfig } from './config/database.config';
import { validateEnv } from './config/env.validation';
import { GlobalExceptionFilter } from './common/filters/global-exception.filter';
import { JwtAuthGuard } from './common/guards/jwt-auth.guard';
import { RolesGuard } from './common/guards/roles.guard';
import { RedisModule } from './infra/redis/redis.module';
import { LiveKitModule } from './infra/livekit/livekit.module';
import { BlobModule } from './infra/blob/blob.module';
import { AuthModule } from './modules/auth/auth.module';
import { UserModule } from './modules/user/user.module';
import { StudentModule } from './modules/student/student.module';
import { SchoolModule } from './modules/school/school.module';
import { DepartmentModule } from './modules/department/department.module';
import { ProfessorModule } from './modules/professor/professor.module';
import { CourseModule } from './modules/course/course.module';
import { EventsModule } from './modules/events/events.module';
import { SessionModule } from './modules/session/session.module';
import { MaterialModule } from './modules/material/material.module';
import { GlossaryModule } from './modules/glossary/glossary.module';
import { QrModule } from './modules/qr/qr.module';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      validate: validateEnv,
    }),
    TypeOrmModule.forRootAsync(typeOrmAsyncConfig),
    // Infra (global)
    RedisModule,
    LiveKitModule,
    BlobModule,
    EventsModule,
    // Domain
    AuthModule,
    UserModule,
    StudentModule,
    SchoolModule,
    DepartmentModule,
    ProfessorModule,
    CourseModule,
    SessionModule,
    MaterialModule,
    GlossaryModule,
    QrModule,
  ],
  providers: [
    { provide: APP_FILTER, useClass: GlobalExceptionFilter },
    { provide: APP_GUARD, useClass: JwtAuthGuard },
    { provide: APP_GUARD, useClass: RolesGuard },
    // @Exclude() 가 붙은 필드(passwordHash 등)를 응답에서 제거
    { provide: APP_INTERCEPTOR, useClass: ClassSerializerInterceptor },
  ],
})
export class AppModule {}
