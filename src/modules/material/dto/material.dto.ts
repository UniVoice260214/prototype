import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import {
  IsEnum,
  IsInt,
  IsOptional,
  IsString,
  IsUUID,
  Min,
} from 'class-validator';
import { Transform } from 'class-transformer';

export class UploadMaterialDto {
  @ApiProperty({ format: 'uuid' })
  @IsUUID()
  courseId: string;

  @ApiPropertyOptional({ format: 'uuid' })
  @IsOptional()
  @IsUUID()
  sessionId?: string;

  @ApiProperty({ enum: ['lecture', 'major'] })
  @IsEnum(['lecture', 'major'])
  sourceType: 'lecture' | 'major';

  @ApiPropertyOptional({ example: 3 })
  @IsOptional()
  @Transform(({ value }) => (value != null ? parseInt(value, 10) : undefined))
  @IsInt()
  @Min(1)
  week?: number;
}

export class StudentMaterialQueryDto {
  @ApiPropertyOptional({
    description:
      'Join token issued from the QR flow. Optional when a Student JWT is used.',
  })
  @IsOptional()
  @IsString()
  joinToken?: string;
}

/** 학생 화면에 노출하는 자료 요약. blobUrl 은 프록시 엔드포인트로 대체된다. */
export class StudentMaterialDto {
  @ApiProperty({ format: 'uuid' })
  id: string;

  @ApiProperty()
  originalFilename: string;

  @ApiProperty({ enum: ['lecture', 'major'] })
  sourceType: 'lecture' | 'major';

  @ApiPropertyOptional({ nullable: true })
  week: number | null;

  @ApiProperty({ enum: ['pending', 'ready', 'failed'] })
  previewStatus: 'pending' | 'ready' | 'failed';

  @ApiProperty()
  createdAt: Date;
}
