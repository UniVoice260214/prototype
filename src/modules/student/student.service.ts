import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { SessionAttendance } from '../session/entities/session-attendance.entity';
import { Student } from './entities/student.entity';
import { UpdateStudentDto } from './dto/update-student.dto';

/** 학생용 "내 수업 목록" 응답 한 줄. */
export interface StudentSessionSummary {
  sessionId: string;
  courseId: string;
  courseName: string;
  status: string;
  startedAt: Date;
  endedAt: Date | null;
  /** 이 수업에서 마지막으로 선택했던 번역 언어. */
  locale: string;
  joinedAt: Date;
}

@Injectable()
export class StudentService {
  constructor(
    @InjectRepository(Student) private readonly students: Repository<Student>,
    @InjectRepository(SessionAttendance)
    private readonly attendances: Repository<SessionAttendance>,
  ) {}

  /** 참여 기록 기반 — 실제로 들어간 수업만 나온다 (자막 열람 권한과 동일 기준). */
  async listMySessions(studentId: string): Promise<StudentSessionSummary[]> {
    const rows = await this.attendances.find({
      where: { studentId },
      relations: { session: { course: true } },
    });
    return rows
      .filter((row) => row.session)
      .sort(
        (a, b) =>
          new Date(b.session.startedAt).getTime() -
          new Date(a.session.startedAt).getTime(),
      )
      .map((row) => ({
        sessionId: row.sessionId,
        courseId: row.session.courseId,
        courseName: row.session.course?.name ?? '',
        status: row.session.status,
        startedAt: row.session.startedAt,
        endedAt: row.session.endedAt,
        locale: row.locale,
        joinedAt: row.joinedAt,
      }));
  }

  findAll(): Promise<Student[]> {
    return this.students.find();
  }

  async findOne(id: string): Promise<Student> {
    const s = await this.students.findOne({ where: { id } });
    if (!s) throw new NotFoundException(`Student ${id} not found`);
    return s;
  }

  async update(id: string, dto: UpdateStudentDto): Promise<Student> {
    const s = await this.findOne(id);
    Object.assign(s, dto);
    return this.students.save(s);
  }

  async remove(id: string): Promise<void> {
    const res = await this.students.delete(id);
    if (!res.affected) throw new NotFoundException(`Student ${id} not found`);
  }
}
