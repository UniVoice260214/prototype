import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { CourseAccessService } from '../../common/access/course-access.service';
import { AuthUser } from '../../common/decorators/current-user.decorator';
import { Course } from './entities/course.entity';
import { CreateCourseDto, UpdateCourseDto } from './dto/course.dto';

@Injectable()
export class CourseService {
  constructor(
    @InjectRepository(Course) private readonly repo: Repository<Course>,
    private readonly courseAccess: CourseAccessService,
  ) {}

  create(dto: CreateCourseDto) {
    return this.repo.save(this.repo.create(dto));
  }

  findAll(
    opts: { departmentId?: string; professorId?: string },
    user: AuthUser,
  ) {
    return this.courseAccess.findCoursesForUser(opts, user);
  }

  findOne(id: string, user: AuthUser) {
    return this.courseAccess.findCourseForUser(id, user);
  }

  async update(id: string, dto: UpdateCourseDto) {
    const c = await this.findOneById(id);
    Object.assign(c, dto);
    return this.repo.save(c);
  }

  async remove(id: string) {
    const res = await this.repo.delete(id);
    if (!res.affected) throw new NotFoundException(`Course ${id} not found`);
  }

  private async findOneById(id: string): Promise<Course> {
    const c = await this.repo.findOne({ where: { id } });
    if (!c) throw new NotFoundException(`Course ${id} not found`);
    return c;
  }
}
