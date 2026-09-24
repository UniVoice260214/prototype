import { Controller, Get, Res } from '@nestjs/common';
import { ApiExcludeController } from '@nestjs/swagger';
import type { Response } from 'express';
import { join } from 'path';
import { Public } from '../../common/decorators/public.decorator';

@Public()
@ApiExcludeController()
@Controller()
export class WebController {
  @Get(['join', 'professor', 'student'])
  serveApp(@Res() response: Response) {
    return response.sendFile(join(process.cwd(), 'public', 'index.html'));
  }
}
