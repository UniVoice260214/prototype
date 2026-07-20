import {
  ForbiddenException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { AuthUser } from '../decorators/current-user.decorator';
import { Course } from '../../modules/course/entities/course.entity';
import { Glossary } from '../../modules/glossary/entities/glossary.entity';
import { Material } from '../../modules/material/entities/material.entity';
import { Professor } from '../../modules/professor/entities/professor.entity';
import { Session } from '../../modules/session/entities/session.entity';

@Injectable()
export class CourseAccessService {
  constructor(
    @InjectRepository(Course) private readonly courses: Repository<Course>,
    @InjectRepository(Glossary)
    private readonly glossaries: Repository<Glossary>,
    @InjectRepository(Material)
    private readonly materials: Repository<Material>,
    @InjectRepository(Professor)
    private readonly professors: Repository<Professor>,
    @InjectRepository(Session) private readonly sessions: Repository<Session>,
  ) {}

  async findCoursesForUser(
    filters: { departmentId?: string; professorId?: string },
    user: AuthUser,
  ): Promise<Course[]> {
    const qb = this.courses.createQueryBuilder('course');

    if (filters.departmentId) {
      qb.andWhere('course.departmentId = :departmentId', {
        departmentId: filters.departmentId,
      });
    }
    if (filters.professorId) {
      qb.andWhere('course.professorId = :requestedProfessorId', {
        requestedProfessorId: filters.professorId,
      });
    }

    if (user.role === 'professor') {
      const professorId = await this.getProfessorProfileId(user);
      qb.andWhere('course.professorId = :viewerProfessorId', {
        viewerProfessorId: professorId,
      });
    }

    return qb.getMany();
  }

  async findCourseForUser(courseId: string, user: AuthUser): Promise<Course> {
    const course = await this.courses.findOne({ where: { id: courseId } });
    if (!course) throw new NotFoundException(`Course ${courseId} not found`);
    await this.assertCanManageCourse(course, user);
    return course;
  }

  async findSessionsForUser(
    filters: { courseId?: string },
    user: AuthUser,
  ): Promise<Session[]> {
    const qb = this.sessions
      .createQueryBuilder('session')
      .innerJoin('session.course', 'course');

    if (filters.courseId) {
      qb.andWhere('session.courseId = :courseId', {
        courseId: filters.courseId,
      });
    }

    if (user.role === 'professor') {
      const professorId = await this.getProfessorProfileId(user);
      qb.andWhere('course.professorId = :viewerProfessorId', {
        viewerProfessorId: professorId,
      });
    }

    return qb.getMany();
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

  async findMaterialsForUser(
    filters: { courseId?: string; sessionId?: string },
    user: AuthUser,
  ): Promise<Material[]> {
    const qb = this.materials
      .createQueryBuilder('material')
      .innerJoin('material.course', 'course');

    if (filters.courseId) {
      qb.andWhere('material.courseId = :courseId', {
        courseId: filters.courseId,
      });
    }
    if (filters.sessionId) {
      qb.andWhere('material.sessionId = :sessionId', {
        sessionId: filters.sessionId,
      });
    }

    if (user.role === 'professor') {
      const professorId = await this.getProfessorProfileId(user);
      qb.andWhere('course.professorId = :viewerProfessorId', {
        viewerProfessorId: professorId,
      });
    }

    return qb.getMany();
  }

  async findMaterialForUser(id: string, user: AuthUser): Promise<Material> {
    const material = await this.materials.findOne({ where: { id } });
    if (!material) throw new NotFoundException(`Material ${id} not found`);
    await this.findCourseForUser(material.courseId, user);
    return material;
  }

  async findGlossariesForUser(
    filters: { courseId?: string },
    user: AuthUser,
  ): Promise<Glossary[]> {
    const qb = this.glossaries
      .createQueryBuilder('glossary')
      .innerJoin('glossary.course', 'course');

    if (filters.courseId) {
      qb.andWhere('glossary.courseId = :courseId', {
        courseId: filters.courseId,
      });
    }

    if (user.role === 'professor') {
      const professorId = await this.getProfessorProfileId(user);
      qb.andWhere('course.professorId = :viewerProfessorId', {
        viewerProfessorId: professorId,
      });
    }

    return qb.getMany();
  }

  async findGlossaryForUser(id: string, user: AuthUser): Promise<Glossary> {
    const glossary = await this.glossaries.findOne({ where: { id } });
    if (!glossary) throw new NotFoundException(`Glossary ${id} not found`);
    await this.findCourseForUser(glossary.courseId, user);
    return glossary;
  }

  async assertCanManageCourse(course: Course, user: AuthUser): Promise<void> {
    if (user.role === 'admin') return;
    if (user.role !== 'professor') {
      throw new ForbiddenException('Professor role is required');
    }

    const professorId = await this.getProfessorProfileId(user);
    if (professorId !== course.professorId) {
      throw new ForbiddenException('Course is not owned by this professor');
    }
  }

  private async getProfessorProfileId(user: AuthUser): Promise<string> {
    if (user.role !== 'professor') {
      throw new ForbiddenException('Professor role is required');
    }

    const professor = await this.professors.findOne({
      where: { userId: user.sub },
    });
    if (!professor) {
      throw new ForbiddenException('Professor profile not found');
    }
    return professor.id;
  }
}
