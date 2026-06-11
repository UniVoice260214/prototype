import {
  Body,
  Controller,
  Delete,
  ForbiddenException,
  Get,
  HttpCode,
  Param,
  ParseUUIDPipe,
  Patch,
} from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiParam, ApiTags } from '@nestjs/swagger';
import {
  AuthUser,
  CurrentUser,
} from '../../common/decorators/current-user.decorator';
import { Roles } from '../../common/decorators/roles.decorator';
import { StudentService } from './student.service';
import { UpdateStudentDto } from './dto/update-student.dto';

@ApiBearerAuth()
@ApiTags('students')
@Controller('students')
export class StudentController {
  constructor(private readonly students: StudentService) {}

  @Roles('admin')
  @Get()
  @ApiOperation({ summary: '학생 목록 조회 (admin)' })
  findAll() {
    return this.students.findAll();
  }

  @Roles('admin', 'student')
  @Get(':studentId')
  @ApiOperation({ summary: '학생 1건 조회 (본인 또는 admin)' })
  @ApiParam({ name: 'studentId', description: '학생(Student) UUID', format: 'uuid' })
  findOne(
    @Param('studentId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    if (user.role === 'student' && user.sub !== id) {
      throw new ForbiddenException('Cannot access other students');
    }
    return this.students.findOne(id);
  }

  @Roles('admin', 'student')
  @Patch(':studentId')
  @ApiOperation({ summary: '학생 정보 수정 (본인 또는 admin)' })
  @ApiParam({ name: 'studentId', description: '학생(Student) UUID', format: 'uuid' })
  update(
    @Param('studentId', ParseUUIDPipe) id: string,
    @Body() dto: UpdateStudentDto,
    @CurrentUser() user: AuthUser,
  ) {
    if (user.role === 'student' && user.sub !== id) {
      throw new ForbiddenException('Cannot update other students');
    }
    return this.students.update(id, dto);
  }

  @Roles('admin')
  @HttpCode(204)
  @Delete(':studentId')
  @ApiOperation({ summary: '학생 삭제 (admin)' })
  @ApiParam({ name: 'studentId', description: '학생(Student) UUID', format: 'uuid' })
  remove(@Param('studentId', ParseUUIDPipe) id: string) {
    return this.students.remove(id);
  }
}
