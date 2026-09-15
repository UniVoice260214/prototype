import {
  BadRequestException,
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
  ApiOkResponse,
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
import {
  IssueStudentTokenDto,
  LiveKitTokenResponseDto,
  PublicSessionInfoDto,
  StartSessionDto,
} from './dto/session.dto';

@ApiBearerAuth()
@ApiTags('sessions')
@Controller('sessions')
export class SessionController {
  constructor(private readonly service: SessionService) {}

  @Roles('professor', 'admin')
  @Post('start')
  @ApiOperation({
    summary: 'Start a session and return the professor LiveKit token',
  })
  start(@Body() dto: StartSessionDto, @CurrentUser() user: AuthUser) {
    return this.service.start(dto, user);
  }

  @Roles('admin', 'professor')
  @Get('active')
  @ApiOperation({
    summary: 'List active sessions visible to the current user',
    description: 'Returns an empty array when there is no active session.',
  })
  @ApiQuery({
    name: 'courseId',
    required: false,
    description: 'Optional course UUID filter',
  })
  findActive(
    @Query('courseId') courseId: string | undefined,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.findActive(courseId, user);
  }

  @Roles('professor', 'admin')
  @Post(':sessionId/end')
  @ApiOperation({ summary: 'End a session and stop its room' })
  @ApiParam({
    name: 'sessionId',
    description: 'Session UUID',
    format: 'uuid',
  })
  end(
    @Param('sessionId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.end(id, user);
  }

  @Public()
  @Get(':sessionId/public')
  @ApiOperation({
    summary: 'Get public session info for the student join screen',
    description:
      'No auth required. Returns only the locales enabled for this session, so the join screen can restrict language choice.',
  })
  @ApiOkResponse({ type: PublicSessionInfoDto })
  @ApiParam({
    name: 'sessionId',
    description: 'Session UUID',
    format: 'uuid',
  })
  findPublic(@Param('sessionId', ParseUUIDPipe) id: string) {
    return this.service.findPublic(id);
  }

  @Public()
  @Post(':sessionId/token')
  @ApiOperation({
    summary: 'Issue a student LiveKit token from a Student JWT or join token',
  })
  @ApiParam({
    name: 'sessionId',
    description: 'Session UUID',
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

  @Roles('professor', 'admin')
  @Post(':sessionId/professor-token')
  @ApiOperation({
    summary: 'Reissue a professor LiveKit token for an active session',
  })
  @ApiOkResponse({ type: LiveKitTokenResponseDto })
  @ApiParam({
    name: 'sessionId',
    description: 'Session UUID',
    format: 'uuid',
  })
  issueProfessorToken(
    @Param('sessionId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.issueProfessorToken(id, user);
  }

  @Roles('admin', 'professor')
  @Get()
  @ApiOperation({ summary: 'List sessions visible to the current user' })
  @ApiQuery({
    name: 'courseId',
    required: false,
    description: 'Optional course UUID filter',
  })
  @ApiQuery({
    name: 'status',
    required: false,
    enum: ['active', 'ended'],
    description: 'Optional status filter (e.g. ended for past-class list)',
  })
  findAll(
    @Query('courseId') courseId: string | undefined,
    @Query('status') status: string | undefined,
    @CurrentUser() user: AuthUser,
  ) {
    if (status !== undefined && status !== 'active' && status !== 'ended') {
      throw new BadRequestException(`Invalid status: ${status}`);
    }
    return this.service.findAll(courseId, status, user);
  }

  @Roles('admin', 'professor')
  @Get(':sessionId/status')
  @ApiOperation({ summary: 'Get session and AI worker status' })
  @ApiParam({
    name: 'sessionId',
    description: 'Session UUID',
    format: 'uuid',
  })
  status(
    @Param('sessionId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.getStatus(id, user);
  }

  @Roles('admin', 'professor')
  @Get(':sessionId')
  @ApiOperation({ summary: 'Get a session visible to the current user' })
  @ApiParam({
    name: 'sessionId',
    description: 'Session UUID',
    format: 'uuid',
  })
  findOne(
    @Param('sessionId', ParseUUIDPipe) id: string,
    @CurrentUser() user: AuthUser,
  ) {
    return this.service.findOne(id, user);
  }
}
