import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { SessionAttendance } from '../session/entities/session-attendance.entity';
import { Student } from './entities/student.entity';
import { StudentService } from './student.service';
import { StudentController } from './student.controller';

@Module({
  imports: [TypeOrmModule.forFeature([Student, SessionAttendance])],
  controllers: [StudentController],
  providers: [StudentService],
  exports: [StudentService],
})
export class StudentModule {}
