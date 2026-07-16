import {
  Body,
  Controller,
  Get,
  Param,
  ParseUUIDPipe,
  Post,
  Query,
} from '@nestjs/common';
import {
  ApiBearerAuth,
  ApiOperation,
  ApiParam,
  ApiQuery,
  ApiTags,
} from '@nestjs/swagger';
import {
  AuthUser,
  CurrentUser,
} from '../../common/decorators/current-user.decorator';
import { Public } from '../../common/decorators/public.decorator';
import { Roles } from '../../common/decorators/roles.decorator';
import { SessionService } from './session.service';
import { IssueStudentTokenDto, StartSessionDto } from './dto/session.dto';

@ApiBearerAuth()
@ApiTags('sessions')
@Controller('sessions')
export class SessionController {
  constructor(private readonly service: SessionService) {}

  @Roles('professor', 'admin')
  @Post('start')
  @ApiOperation({
    summary:
      '세션 시작: LiveKit Room 생성 + Redis prewarm + 워커 이벤트 발행 + 교수 token 반환',
  })
  start(@Body() dto: StartSessionDto, @CurrentUser() user: AuthUser) {
    return this.service.start(dto, user);
  }

  @Roles('professor', 'admin')
  @Post(':sessionId/end')
  @ApiOperation({ summary: '세션 종료 (Room 삭제 + sessions.ended 이벤트)' })
  @ApiParam({
    name: 'sessionId',
    description: '세션(Session) UUID',
    format: 'uuid',
  })
  end(
    @Param('sessionId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.end(id, user);
  }

  @Public() // JoinToken으로도 접근 가능. 인증된 Student JWT면 더 안전.
  @Post(':sessionId/token')
  @ApiOperation({
    summary:
      '학생 LiveKit token 발급 (JoinToken 또는 Student JWT 필요, locale 지정)',
  })
  @ApiParam({
    name: 'sessionId',
    description: '세션(Session) UUID',
    format: 'uuid',
  })
  issueStudentToken(
    @Param('sessionId', ParseUUIDPipe) id: string,
    @Body() dto: IssueStudentTokenDto,
    @CurrentUser() user: AuthUser | undefined,
  ) {
    const studentId = user?.type === 'student' ? user.sub : null;
    return this.service.issueStudentToken(id, dto, studentId);
  }

  @Get()
  @ApiOperation({ summary: '세션 목록 조회 (courseId로 필터링 가능)' })
  @ApiQuery({
    name: 'courseId',
    required: false,
    description: '과목 UUID 필터',
  })
  findAll(@Query('courseId') courseId?: string) {
    return this.service.findAll(courseId);
  }

  @Get(':sessionId')
  @ApiOperation({ summary: '세션 1건 조회' })
  @ApiParam({
    name: 'sessionId',
    description: '세션(Session) UUID',
    format: 'uuid',
  })
  findOne(@Param('sessionId', ParseUUIDPipe) id: string) {
    return this.service.findOne(id);
  }
}
