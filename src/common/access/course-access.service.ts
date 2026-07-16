import {
  ForbiddenException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { AuthUser } from '../decorators/current-user.decorator';
import { Course } from '../../modules/course/entities/course.entity';
import { Professor } from '../../modules/professor/entities/professor.entity';
import { Session } from '../../modules/session/entities/session.entity';

@Injectable()
export class CourseAccessService {
  constructor(
    @InjectRepository(Course) private readonly courses: Repository<Course>,
    @InjectRepository(Professor)
    private readonly professors: Repository<Professor>,
    @InjectRepository(Session) private readonly sessions: Repository<Session>,
  ) {}

  async findCourseForUser(courseId: string, user: AuthUser): Promise<Course> {
    const course = await this.courses.findOne({ where: { id: courseId } });
    if (!course) throw new NotFoundException(`Course ${courseId} not found`);
    await this.assertCanManageCourse(course, user);
    return course;
  }

  async findSessionForUser(
    sessionId: string,
    user: AuthUser,
  ): Promise<Session> {
    const session = await this.sessions.findOne({ where: { id: sessionId } });
    if (!session) throw new NotFoundException(`Session ${sessionId} not found`);
    await this.findCourseForUser(session.courseId, user);
    return session;
  }

  async assertCanManageCourse(course: Course, user: AuthUser): Promise<void> {
    if (user.role === 'admin') return;
    if (user.role !== 'professor') {
      throw new ForbiddenException('Professor role is required');
    }

    const professor = await this.professors.findOne({
      where: { userId: user.sub },
    });
    if (!professor || professor.id !== course.professorId) {
      throw new ForbiddenException('Course is not owned by this professor');
    }
  }
}
