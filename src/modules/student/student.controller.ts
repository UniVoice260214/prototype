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
  @ApiOperation({ summary: 'List all students' })
  findAll() {
    return this.students.findAll();
  }

  @Roles('student')
  @Get('me/sessions')
  @ApiOperation({
    summary: 'List sessions the logged-in student attended (newest first)',
  })
  listMySessions(@CurrentUser() user: AuthUser) {
    return this.students.listMySessions(user.sub);
  }

  @Roles('admin', 'student')
  @Get(':studentId')
  @ApiOperation({ summary: 'Get a student profile (self or admin)' })
  @ApiParam({
    name: 'studentId',
    description: 'Student UUID',
    format: 'uuid',
  })
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
  @ApiOperation({ summary: 'Update a student profile (self or admin)' })
  @ApiParam({
    name: 'studentId',
    description: 'Student UUID',
    format: 'uuid',
  })
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
  @ApiOperation({ summary: 'Delete a student' })
  @ApiParam({
    name: 'studentId',
    description: 'Student UUID',
    format: 'uuid',
  })
  remove(@Param('studentId', ParseUUIDPipe) id: string) {
    return this.students.remove(id);
  }
}
