import {
  BadRequestException,
  ConflictException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { Professor } from './entities/professor.entity';
import { User } from '../user/entities/user.entity';
import { CreateProfessorDto, UpdateProfessorDto } from './dto/professor.dto';

@Injectable()
export class ProfessorService {
  constructor(
    @InjectRepository(Professor) private readonly repo: Repository<Professor>,
    @InjectRepository(User) private readonly users: Repository<User>,
  ) {}

  async create(dto: CreateProfessorDto): Promise<Professor> {
    const user = await this.users.findOne({ where: { id: dto.userId } });
    if (!user) throw new NotFoundException(`User ${dto.userId} not found`);
    if (user.role !== 'professor') {
      throw new BadRequestException('User role must be professor');
    }
    const exists = await this.repo.findOne({ where: { userId: dto.userId } });
    if (exists) {
      throw new ConflictException(
        'Professor profile already exists for this user',
      );
    }
    return this.repo.save(this.repo.create(dto));
  }

  findAll(departmentId?: string) {
    return this.repo.find({
      where: departmentId ? { departmentId } : {},
      relations: { user: true },
    });
  }

  async findOne(id: string): Promise<Professor> {
    const p = await this.repo.findOne({
      where: { id },
      relations: { user: true },
    });
    if (!p) throw new NotFoundException(`Professor ${id} not found`);
    return p;
  }

  async update(id: string, dto: UpdateProfessorDto): Promise<Professor> {
    const p = await this.findOne(id);
    Object.assign(p, dto);
    return this.repo.save(p);
  }

  async remove(id: string): Promise<void> {
    const res = await this.repo.delete(id);
    if (!res.affected) throw new NotFoundException(`Professor ${id} not found`);
  }
}
