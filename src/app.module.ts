import { ClassSerializerInterceptor, Module } from '@nestjs/common';
import { APP_FILTER, APP_GUARD, APP_INTERCEPTOR } from '@nestjs/core';
import { ConfigModule } from '@nestjs/config';
import { TypeOrmModule } from '@nestjs/typeorm';
import { GlobalExceptionFilter } from './common/filters/global-exception.filter';
import { JwtAuthGuard } from './common/guards/jwt-auth.guard';
import { RolesGuard } from './common/guards/roles.guard';
import { typeOrmAsyncConfig } from './config/database.config';
import { validateEnv } from './config/env.validation';
import { BlobModule } from './infra/blob/blob.module';
import { LiveKitModule } from './infra/livekit/livekit.module';
import { RedisModule } from './infra/redis/redis.module';
import { AuthModule } from './modules/auth/auth.module';
import { CourseModule } from './modules/course/course.module';
import { DepartmentModule } from './modules/department/department.module';
import { EventsModule } from './modules/events/events.module';
import { GlossaryModule } from './modules/glossary/glossary.module';
import { MaterialModule } from './modules/material/material.module';
import { ProfessorModule } from './modules/professor/professor.module';
import { QrModule } from './modules/qr/qr.module';
import { SchoolModule } from './modules/school/school.module';
import { SessionModule } from './modules/session/session.module';
import { StudentModule } from './modules/student/student.module';
import { UserModule } from './modules/user/user.module';
import { WebModule } from './modules/web/web.module';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      validate: validateEnv,
    }),
    TypeOrmModule.forRootAsync(typeOrmAsyncConfig),
    // Global infrastructure
    RedisModule,
    LiveKitModule,
    BlobModule,
    EventsModule,
    // Domain modules
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
    WebModule,
  ],
  providers: [
    { provide: APP_FILTER, useClass: GlobalExceptionFilter },
    { provide: APP_GUARD, useClass: JwtAuthGuard },
    { provide: APP_GUARD, useClass: RolesGuard },
    // Remove excluded fields such as password hashes from serialized responses.
    { provide: APP_INTERCEPTOR, useClass: ClassSerializerInterceptor },
  ],
})
export class AppModule {}
