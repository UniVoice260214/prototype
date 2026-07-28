import {
  ConflictException,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { JwtService, JwtSignOptions } from '@nestjs/jwt';
import { InjectRepository } from '@nestjs/typeorm';
import * as bcrypt from 'bcrypt';
import { Repository } from 'typeorm';
import { Student } from '../student/entities/student.entity';
import { User } from '../user/entities/user.entity';
import { LoginDto, TokenResponseDto } from './dto/login.dto';
import { SignupStudentDto } from './dto/signup-student.dto';

const BCRYPT_ROUNDS = 10;

@Injectable()
export class AuthService {
  constructor(
    @InjectRepository(User) private readonly users: Repository<User>,
    @InjectRepository(Student) private readonly students: Repository<Student>,
    private readonly jwt: JwtService,
    private readonly config: ConfigService,
  ) {}

  async loginUser(dto: LoginDto): Promise<TokenResponseDto> {
    const user = await this.users.findOne({ where: { email: dto.email } });
    if (!user) throw new UnauthorizedException('Invalid credentials');

    const ok = await bcrypt.compare(dto.password, user.passwordHash);
    if (!ok) throw new UnauthorizedException('Invalid credentials');

    const accessToken = await this.jwt.signAsync(
      { sub: user.id, role: user.role, type: 'user' },
      this.signOpts('JWT_EXPIRES_IN', '1d'),
    );
    return { accessToken, tokenType: 'Bearer', role: user.role };
  }

  async signupStudent(dto: SignupStudentDto): Promise<TokenResponseDto> {
    const exists = await this.students.findOne({ where: { email: dto.email } });
    if (exists) throw new ConflictException('Email already registered');

    const passwordHash = await bcrypt.hash(dto.password, BCRYPT_ROUNDS);
    const student = await this.students.save(
      this.students.create({
        email: dto.email,
        passwordHash,
        name: dto.name,
        preferredLocale: dto.preferredLocale ?? null,
      }),
    );
    return this.signStudentToken(student.id);
  }

  async loginStudent(dto: LoginDto): Promise<TokenResponseDto> {
    const student = await this.students.findOne({ where: { email: dto.email } });
    if (!student) throw new UnauthorizedException('Invalid credentials');

    const ok = await bcrypt.compare(dto.password, student.passwordHash);
    if (!ok) throw new UnauthorizedException('Invalid credentials');

    return this.signStudentToken(student.id);
  }

  async signJoinToken(
    sessionId: string,
    studentId: string | 'guest' = 'guest',
  ): Promise<string> {
    return this.jwt.signAsync(
      { sub: studentId, sessionId, type: 'session-join' },
      this.signOpts('JWT_JOIN_TOKEN_EXPIRES_IN', '24h'),
    );
  }

  async verifyJoinToken(token: string): Promise<{ sub: string; sessionId: string }> {
    try {
      const payload = await this.jwt.verifyAsync<{
        sub: string;
        sessionId: string;
        type: string;
      }>(token);
      if (payload.type !== 'session-join') {
        throw new UnauthorizedException('Not a join token');
      }
      return { sub: payload.sub, sessionId: payload.sessionId };
    } catch {
      throw new UnauthorizedException('Invalid or expired join token');
    }
  }

  private signOpts(envKey: string, fallback: string): JwtSignOptions {
    return {
      expiresIn: this.config.get<string>(
        envKey,
        fallback,
      ) as JwtSignOptions['expiresIn'],
    };
  }

  private async signStudentToken(
    studentId: string,
  ): Promise<TokenResponseDto> {
    const accessToken = await this.jwt.signAsync(
      { sub: studentId, role: 'student', type: 'student' },
      this.signOpts('JWT_EXPIRES_IN', '1d'),
    );
    return { accessToken, tokenType: 'Bearer', role: 'student' };
  }
}
